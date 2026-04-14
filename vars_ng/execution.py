import abc
import http.server
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional

from .models import GeneratorConfig, FileConfig
from .utils import get_file_dest_path


class HttpError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


class UnixSocketHttpServer(socketserver.UnixStreamServer):
    def get_request(self):
        request, client_address = super().get_request()
        return (request, ["local", 0])


def make_handler(generators: Dict[str, GeneratorConfig], output_dir: str):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress logging

        def _get_file_config(self) -> FileConfig:
            parts = self.path.strip("/").split("/")
            if len(parts) != 2:
                raise HttpError(400, "Bad Request")

            var_name, file_name = parts
            var = generators.get(var_name)
            if not var:
                raise HttpError(404, "Generator not found")

            for file_config in var["files"].values():
                if file_config["name"] == file_name:
                    return file_config

            raise HttpError(404, "File not found in generator")

        def do_GET(self):
            try:
                file_config = self._get_file_config()
            except HttpError as e:
                self.send_error(e.code, e.message)
                return

            path = get_file_dest_path(output_dir, file_config)
            if not path.exists():
                self.send_error(404, "File not generated yet")
                return

            self.send_response(200)
            self.send_header("Content-type", "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)

        def do_POST(self):
            try:
                file_config = self._get_file_config()
            except HttpError as e:
                self.send_error(e.code, e.message)
                return

            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)

            dest_path = get_file_dest_path(output_dir, file_config)
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                f.write(post_data)

            mode_str = file_config.get("mode")
            if mode_str:
                try:
                    dest_path.chmod(int(mode_str, 8))
                except ValueError:
                    print(
                        f"Warning: Invalid mode '{mode_str}' for {file_config['name']}"
                    )

            self.send_response(200)
            self.end_headers()

    return Handler


class GeneratorRunner(abc.ABC):
    """
    Abstract base class for executing configuration generators.

    Provides a context manager interface for setting up and tearing down
    any necessary execution environment (like temporary directories or servers).
    """

    def __init__(
        self,
        generators: Dict[str, GeneratorConfig],
        output_dir: str,
        nixpkgs_path: Optional[str],
    ):
        self.generators = generators
        self.output_dir = output_dir
        self.nixpkgs_path = nixpkgs_path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @abc.abstractmethod
    def generate(self, var_name: str, var: GeneratorConfig) -> None:
        pass


class LocalRunner(GeneratorRunner):
    """
    Executes generators locally without isolation.

    Uses standard temporary directories to provide inputs and capture outputs.
    Dependencies are copied directly on the host filesystem. This is useful for
    testing or environments where Nix sandboxing is unavailable.
    """

    def generate(self, var_name: str, var: GeneratorConfig) -> None:
        """Runs the specified generator without a nix sandbox (using temporary directories directly)."""
        old_umask = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as temp_dir_str:
                temp_dir = Path(temp_dir_str)
                in_dir = temp_dir / "in"
                out_dir = temp_dir / "out"
                in_dir.mkdir()
                out_dir.mkdir()

                # Set up inputs from dependencies
                for dep_name in var["dependencies"]:
                    dep_gen = self.generators[dep_name]
                    dep_dir = in_dir / dep_name
                    dep_dir.mkdir(exist_ok=True)
                    for file_config in dep_gen["files"].values():
                        src_path = get_file_dest_path(self.output_dir, file_config)
                        dest_path = dep_dir / file_config["name"]
                        if src_path.exists():
                            shutil.copy2(src_path, dest_path)

                # Prepare environment
                env = os.environ.copy()
                env["in"] = str(in_dir)
                env["out"] = str(out_dir)

                # Prepare PATH with runtimeInputs
                runtime_inputs = var["runtimeInputs"]
                bin_paths = [str(Path(p) / "bin") for p in runtime_inputs]
                if bin_paths:
                    env["PATH"] = ":".join(bin_paths)

                # Write and execute script
                script_content = var["script"]
                script_path = temp_dir / "script.sh"
                script_path.write_text(
                    f"#!/usr/bin/env bash\nset -euo pipefail\numask 077\n{script_content}"
                )
                script_path.chmod(script_path.stat().st_mode | 0o111)

                try:
                    subprocess.run(
                        [str(script_path)], env=env, check=True, cwd=str(temp_dir)
                    )
                except subprocess.CalledProcessError:
                    print(f"Error executing script for generator {var_name}")
                    exit(1)

                # Move generated files to destination
                for file_config in var["files"].values():
                    name = file_config["name"]
                    dest_path = get_file_dest_path(self.output_dir, file_config)

                    src_file = out_dir / name
                    if src_file.exists():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src_file), str(dest_path))

                        # Set mode
                        mode_str = file_config["mode"]
                        if mode_str:
                            try:
                                dest_path.chmod(int(mode_str, 8))
                            except ValueError:
                                print(f"Warning: Invalid mode '{mode_str}' for {name}")
        finally:
            os.umask(old_umask)


class SandboxRunner(GeneratorRunner):
    """
    Executes generators strictly isolated within a Nix sandbox.

    Starts a background HTTP server listening on a Unix domain socket. The
    sandboxed generator script uses `curl` over this socket to fetch its
    declared dependencies and to upload its generated outputs back to the host.
    """

    def __enter__(self):
        self.tmpdir = Path("/tmp/sandbox-test")
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.tmpdir.chmod(0o777)

        self.socket_path = self.tmpdir / "vars.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.server = UnixSocketHttpServer(
            str(self.socket_path), make_handler(self.generators, self.output_dir)
        )
        os.chmod(str(self.socket_path), 0o777)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.server.shutdown()
        self.server.server_close()

    def generate(
        self,
        var_name: str,
        var: GeneratorConfig,
    ) -> None:
        """Runs the specified generator inside a nix sandbox using a unix socket to fetch/write files."""
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            # Construct the bash script to execute inside the sandbox
            setup_script = ["export in=$(mktemp -d)", "export out=$(mktemp -d)"]

            # Fetch dependencies
            for dep_name in var["dependencies"]:
                dep_gen = self.generators[dep_name]
                setup_script.append(f"mkdir -p $in/{dep_name}")
                for file_config in dep_gen["files"].values():
                    file_name = file_config["name"]
                    setup_script.append(
                        f"curl --fail -s --unix-socket {self.socket_path} http://localhost/{dep_name}/{file_name} -o $in/{dep_name}/{file_name}"
                    )

            script_content = var["script"]

            # Upload outputs
            upload_script = []
            for file_config in var["files"].values():
                file_name = file_config["name"]
                upload_script.append(
                    f"curl --fail -s -X POST --unix-socket {self.socket_path} --data-binary @$out/{file_name} http://localhost/{var_name}/{file_name}"
                )

            full_script = (
                "set -euo pipefail\n"
                + "\n(" # run in a subshell to avoid overwriting the Nix environment's $out
                + "\n".join(setup_script)
                + "\n"
                + script_content
                + "\n".join(upload_script)
                + "\n)\n"
                + "mkdir -p $out\n"
            )

            runtime_inputs_str = " ".join(var["runtimeInputs"])
            nixpkgs = self.nixpkgs_path or "<nixpkgs>"

            nix_expr = f"""
            let
              pkgs = import {nixpkgs} {{}};
            in
            pkgs.runCommand "vars-generator-{var_name}" {{
              buildInputs = [ pkgs.curl ] ++ [ {runtime_inputs_str} ];
            }} ''
              {full_script}
            ''
            """

            expr_path = temp_dir / "expr.nix"
            expr_path.write_text(nix_expr)

            cmd = [
                "nix-build",
                "--no-out-link",
                "--option",
                "extra-sandbox-paths",
                str(self.socket_path),
                str(expr_path),
            ]

            env = os.environ.copy()
            if self.nixpkgs_path:
                env["NIX_PATH"] = f"nixpkgs={self.nixpkgs_path}"

            try:
                subprocess.run(cmd, env=env, check=True)
            except subprocess.CalledProcessError:
                print(f"Error executing script for generator {var_name}")
                exit(1)
