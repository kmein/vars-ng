import abc
import http.server
import hmac
import os
import secrets
import shutil
import socketserver
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from .models import GeneratorConfig, FileConfig, BackendConfig


# Max request body the daemon will accept from a sandboxed script (per POST).
# Generator/file/dependency names and runtimeInputs shape are enforced by the
# nixos module (options.nix), so python trusts them as safe to interpolate.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


class HttpError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


@dataclass
class TokenGrant:
    """What a single bearer token is allowed to do.

    reads: set of (generator_name, file_name) this token may GET
    writes: set of (generator_name, file_name) this token may POST
    """

    generator: str
    reads: Set[Tuple[str, str]] = field(default_factory=set)
    writes: Set[Tuple[str, str]] = field(default_factory=set)


class UnixSocketHttpServer(socketserver.UnixStreamServer):
    def get_request(self):
        request, _client_address = super().get_request()
        return (request, ("local", 0))


def make_handler(
    generators: Dict[str, GeneratorConfig],
    gen_to_backend: Dict[str, BackendConfig],
    tokens: Dict[str, TokenGrant],
    tokens_lock: threading.Lock,
):
    def _lookup_token(auth_header: Optional[str]) -> TokenGrant:
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HttpError(401, "Missing bearer token")
        presented = auth_header[len("Bearer ") :].strip()
        with tokens_lock:
            # Constant-time compare against every live token to avoid leaking
            # which prefix matched via timing.
            for tok, grant in tokens.items():
                if hmac.compare_digest(tok, presented):
                    return grant
        raise HttpError(403, "Unknown or revoked token")

    def _parse_path(path: str) -> Tuple[str, str]:
        parts = path.strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            raise HttpError(400, "Bad Request")
        return parts[0], parts[1]

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress default stderr access log

        def _get_file_config(self, gen_name: str, file_name: str) -> FileConfig:
            var = generators.get(gen_name)
            if not var:
                raise HttpError(404, "Generator not found")
            for file_config in var["files"].values():
                if file_config["name"] == file_name:
                    return file_config
            raise HttpError(404, "File not found in generator")

        def do_GET(self):
            try:
                grant = _lookup_token(self.headers.get("Authorization"))
                gen_name, file_name = _parse_path(self.path)
                if (gen_name, file_name) not in grant.reads:
                    raise HttpError(403, "Read not permitted for this token")
                _ = self._get_file_config(gen_name, file_name)
            except HttpError as e:
                self.send_error(e.code, e.message)
                return

            backend = gen_to_backend[gen_name]

            with tempfile.NamedTemporaryFile() as tmp:
                try:
                    subprocess.run(
                        ["bash", "-c", backend["get"], "--", gen_name, file_name],
                        env={"out": tmp.name},
                        check=True,
                        capture_output=True,
                    )
                except subprocess.CalledProcessError as e:
                    self.send_error(
                        500,
                        f"Backend get failed: {e.stderr.decode() if e.stderr else 'unknown'}",
                    )
                    return

                size = os.path.getsize(tmp.name)
                self.send_response(200)
                self.send_header("Content-type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.end_headers()

                with open(tmp.name, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)

        def do_POST(self):
            try:
                grant = _lookup_token(self.headers.get("Authorization"))
                gen_name, file_name = _parse_path(self.path)
                if (gen_name, file_name) not in grant.writes:
                    raise HttpError(403, "Write not permitted for this token")
                _ = self._get_file_config(gen_name, file_name)
            except HttpError as e:
                self.send_error(e.code, e.message)
                return

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length < 0 or content_length > MAX_UPLOAD_BYTES:
                self.send_error(413, "Payload too large")
                return
            post_data = self.rfile.read(content_length)

            backend = gen_to_backend[gen_name]

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                try:
                    tmp.write(post_data)
                    tmp.close()

                    subprocess.run(
                        ["bash", "-c", backend["set"], "--", gen_name, file_name],
                        env={"in": tmp.name},
                        check=True,
                        capture_output=True,
                    )
                except subprocess.CalledProcessError as e:
                    self.send_error(
                        500,
                        f"Backend set failed: {e.stderr.decode() if e.stderr else 'unknown'}",
                    )
                    return
                finally:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)

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
        gen_to_backend: Dict[str, BackendConfig],
        nixpkgs_path: Optional[str],
    ):
        self.generators = generators
        self.gen_to_backend = gen_to_backend
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
                    backend = self.gen_to_backend[dep_name]
                    for file_config in dep_gen["files"].values():
                        name = file_config["name"]
                        dest_path = dep_dir / name
                        try:
                            subprocess.run(
                                ["bash", "-c", backend["get"], "--", dep_name, name],
                                env={"out": str(dest_path)},
                                check=True,
                            )
                        except subprocess.CalledProcessError:
                            print(
                                f"Error fetching dependency {dep_name}/{name} using backend"
                            )
                            exit(1)

                # Prepare environment
                env = os.environ.copy()
                env["in"] = str(in_dir)
                env["out"] = str(out_dir)

                # Prepare PATH with runtimeInputs
                runtime_inputs = var["runtimeInputs"]
                bin_paths = [str(Path(p) / "bin") for p in runtime_inputs]
                if bin_paths:
                    env["PATH"] = ":".join(bin_paths) + ":" + env.get("PATH", "")

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
                backend = self.gen_to_backend[var_name]
                for file_config in var["files"].values():
                    name = file_config["name"]
                    src_file = out_dir / name
                    if src_file.exists():
                        mode_str = file_config["mode"]
                        if mode_str:
                            try:
                                src_file.chmod(int(mode_str, 8))
                            except ValueError:
                                print(f"Warning: Invalid mode '{mode_str}' for {name}")

                        try:
                            subprocess.run(
                                ["bash", "-c", backend["set"], "--", var_name, name],
                                env={"in": str(src_file)},
                                check=True,
                            )
                        except subprocess.CalledProcessError:
                            print(
                                f"Error setting output {var_name}/{name} using backend"
                            )
                            exit(1)
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
        # Unique dir per run, owned by current user. Short path so the unix
        # socket stays under the ~104 byte sun_path limit.
        self.tmpdir = Path(tempfile.mkdtemp(prefix="vars-ng-", dir="/tmp"))
        os.chmod(self.tmpdir, 0o755)

        self.socket_path = self.tmpdir / "vars.sock"
        self.tokens: Dict[str, TokenGrant] = {}
        self.tokens_lock = threading.Lock()

        self.server = UnixSocketHttpServer(
            str(self.socket_path),
            make_handler(
                self.generators, self.gen_to_backend, self.tokens, self.tokens_lock
            ),
        )
        # Socket must be reachable by the nix build user, which is not us.
        # Auth token (not filesystem perms) is what actually gates access.
        os.chmod(str(self.socket_path), 0o666)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mint_token(self, var_name: str, var: GeneratorConfig) -> str:
        """Create a scoped bearer token for one generator run."""
        token = secrets.token_urlsafe(32)
        grant = TokenGrant(generator=var_name)
        for dep_name in var["dependencies"]:
            dep_gen = self.generators[dep_name]
            for file_config in dep_gen["files"].values():
                grant.reads.add((dep_name, file_config["name"]))
        for file_config in var["files"].values():
            grant.writes.add((var_name, file_config["name"]))
        with self.tokens_lock:
            self.tokens[token] = grant
        return token

    def _revoke_token(self, token: str) -> None:
        with self.tokens_lock:
            self.tokens.pop(token, None)

    def generate(
        self,
        var_name: str,
        var: GeneratorConfig,
    ) -> None:
        """Runs the specified generator inside a nix sandbox using a unix socket to fetch/write files."""
        token = self._mint_token(var_name, var)
        try:
            self._run_nix_build(var_name, var, token)
        finally:
            self._revoke_token(token)

    def _run_nix_build(self, var_name: str, var: GeneratorConfig, token: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            # Curl invocations share these flags. -H passes the bearer token,
            # which the daemon matches against the per-run token table.
            curl_base = (
                f"curl --fail -sS --unix-socket {self.socket_path} "
                f'-H "Authorization: Bearer $VARS_TOKEN"'
            )

            setup_script = [
                f"export VARS_TOKEN={token}",
                "export in=$(mktemp -d)",
                "export out=$(mktemp -d)",
            ]

            for dep_name in var["dependencies"]:
                dep_gen = self.generators[dep_name]
                setup_script.append(f"mkdir -p $in/{dep_name}")
                for file_config in dep_gen["files"].values():
                    file_name = file_config["name"]
                    setup_script.append(
                        f"{curl_base} http://localhost/{dep_name}/{file_name} "
                        f"-o $in/{dep_name}/{file_name}"
                    )

            upload_script = []
            for file_config in var["files"].values():
                file_name = file_config["name"]
                upload_script.append(
                    f"{curl_base} -X POST --data-binary @$out/{file_name} "
                    f"http://localhost/{var_name}/{file_name}"
                )

            # Subshell keeps our $out redefinition from clobbering Nix's $out.
            bash = (
                "set -euo pipefail\n"
                "(\n"
                + "\n".join(setup_script)
                + "\n"
                + var["script"].rstrip("\n")
                + "\n"
                + "\n".join(upload_script)
                + "\n)\n"
                "mkdir -p $out\n"
            )
            # Escape for nix indented string: '' terminates, ${...} antiquotes.
            full_script = bash.replace("''", "'''").replace("${", "''${")

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
