import http.server
import hmac
import json
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

from .evaluator import runner_expr
from .models import GeneratorConfig, FileConfig, Backend
from .utils import VarsError


# Max upload the daemon will accept from a generator script.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


class HttpError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


@dataclass
class TokenGrant:
    """Bearer-token capabilities for a single generator run.

    reads/writes are sets of (generator_name, file_name) pairs.
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
    gen_to_backend: Dict[str, str],
    backends: Dict[str, Backend],
    tokens: Dict[str, TokenGrant],
    tokens_lock: threading.Lock,
    assume_yes: bool,
):
    def _lookup_token(auth_header: Optional[str]) -> TokenGrant:
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HttpError(401, "Missing bearer token")
        presented = auth_header[len("Bearer ") :].strip()
        with tokens_lock:
            for tok, grant in tokens.items():
                if hmac.compare_digest(tok, presented):
                    return grant
        raise HttpError(403, "Unknown or revoked token")

    def _parse_path(path: str) -> Tuple[str, str]:
        parts = path.strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            raise HttpError(400, "Bad Request")
        return parts[0], parts[1]

    def _file_config(gen_name: str, file_name: str) -> FileConfig:
        var = generators.get(gen_name)
        if not var:
            raise HttpError(404, "Generator not found")
        for fc in var["files"].values():
            if fc["name"] == file_name:
                return fc
        raise HttpError(404, "File not found in generator")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            try:
                grant = _lookup_token(self.headers.get("Authorization"))
                gen_name, file_name = _parse_path(self.path)
                if (gen_name, file_name) not in grant.reads:
                    raise HttpError(403, "Read not permitted for this token")
                _file_config(gen_name, file_name)
            except HttpError as e:
                self.send_error(e.code, e.message)
                return

            backend = backends[gen_to_backend[gen_name]]
            with tempfile.NamedTemporaryFile() as tmp:
                try:
                    backend.get(
                        gen_name=gen_name,
                        file_name=file_name,
                        out_path=tmp.name,
                        assume_yes=assume_yes,
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
                fc = _file_config(gen_name, file_name)
            except HttpError as e:
                self.send_error(e.code, e.message)
                return

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length < 0 or content_length > MAX_UPLOAD_BYTES:
                self.send_error(413, "Payload too large")
                return
            body = self.rfile.read(content_length)

            backend = backends[gen_to_backend[gen_name]]
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                try:
                    tmp.write(body)
                    tmp.close()
                    if fc["mode"]:
                        try:
                            os.chmod(tmp.name, int(fc["mode"], 8))
                        except ValueError:
                            pass
                    backend.set(
                        gen_name=gen_name,
                        file_name=file_name,
                        in_path=tmp.name,
                        assume_yes=assume_yes,
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


class Runner:
    """Realizes generator runners (Nix derivations) and executes them.

    A single background HTTP daemon serves dependency reads and output
    uploads over a unix socket; the runner script (composed in Nix from
    `vars.generators.<name>.runner`) talks to it via curl. In sandbox
    mode the runner is invoked from inside a tiny `runCommand` so the
    nix sandbox isolates it; in local mode it is exec'd directly.
    """

    def __init__(
        self,
        generators: Dict[str, GeneratorConfig],
        gen_to_backend: Dict[str, str],
        backends: Dict[str, Backend],
        configuration_path: Path,
        nixpkgs_path: Optional[str],
        sandbox: bool,
        assume_yes: bool = False,
    ):
        self.generators = generators
        self.gen_to_backend = gen_to_backend
        self.backends = backends
        self.configuration_path = configuration_path
        self.nixpkgs_path = nixpkgs_path
        self.sandbox = sandbox
        self.assume_yes = assume_yes
        self.tokens: Dict[str, TokenGrant] = {}
        self.tokens_lock = threading.Lock()
        self._runner_cache: Dict[str, str] = {}

    def __enter__(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="vars-ng-", dir="/tmp"))
        os.chmod(self.tmpdir, 0o755)
        self.socket_path = self.tmpdir / "vars.sock"

        self.server = UnixSocketHttpServer(
            str(self.socket_path),
            make_handler(
                self.generators,
                self.gen_to_backend,
                self.backends,
                self.tokens,
                self.tokens_lock,
                self.assume_yes,
            ),
        )
        # The socket must be reachable by the nix build user (a different uid
        # in sandbox mode); the bearer token, not the file mode, gates access.
        os.chmod(str(self.socket_path), 0o666)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mint_token(self, var_name: str, var: GeneratorConfig) -> str:
        token = secrets.token_urlsafe(32)
        grant = TokenGrant(generator=var_name)
        for dep_name in var["dependencies"]:
            for fc in self.generators[dep_name]["files"].values():
                grant.reads.add((dep_name, fc["name"]))
        for fc in var["files"].values():
            grant.writes.add((var_name, fc["name"]))
        with self.tokens_lock:
            self.tokens[token] = grant
        return token

    def _revoke_token(self, token: str) -> None:
        with self.tokens_lock:
            self.tokens.pop(token, None)

    def _runner_script(self, var_name: str) -> str:
        """Evaluates the per-generator runner script (a string) from Nix.

        The script is composed in Nix using lib.makeBinPath, lib.concatMapStringsSep,
        etc. — Python does not assemble bash. Nothing is built; only evaluation.
        """
        if var_name in self._runner_cache:
            return self._runner_cache[var_name]
        expr = runner_expr(self.configuration_path, self.nixpkgs_path, var_name)
        env = os.environ.copy()
        if self.nixpkgs_path:
            env["NIX_PATH"] = f"nixpkgs={self.nixpkgs_path}"
        try:
            result = subprocess.run(
                ["nix-instantiate", "--eval", "--json", "--strict", "-E", expr],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise VarsError(
                f"Failed to evaluate runner for {var_name}:\n{e.stderr or e.stdout}"
            )
        script: str = json.loads(result.stdout)
        self._runner_cache[var_name] = script
        return script

    def generate(self, var_name: str, var: GeneratorConfig, assume_yes: bool) -> None:
        script = self._runner_script(var_name)
        token = self._mint_token(var_name, var)
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".sh", delete=False, dir=str(self.tmpdir)
            ) as f:
                f.write(script)
                runner_path = f.name
            os.chmod(runner_path, 0o755)
            if self.sandbox:
                self._run_sandboxed(runner_path, token)
            else:
                self._run_local(runner_path, token)
        except subprocess.CalledProcessError:
            raise VarsError(f"Error executing script for generator {var_name}")
        finally:
            self._revoke_token(token)

    def _run_local(self, runner_path: str, token: str) -> None:
        env = os.environ.copy()
        env["VARS_SOCKET"] = str(self.socket_path)
        env["VARS_TOKEN"] = token
        old_umask = os.umask(0o077)
        try:
            subprocess.run([runner_path], env=env, check=True)
        finally:
            os.umask(old_umask)

    def _run_sandboxed(self, runner_path: str, token: str) -> None:
        nixpkgs = self.nixpkgs_path or "<nixpkgs>"
        # Tiny static wrapper: one runCommand per generator-run, no
        # per-generator script templating. The token enters the derivation
        # hash (--argstr) so concurrent runs don't collide; both the socket
        # and the runner script are allowed via extra-sandbox-paths.
        expr = f"""
{{ runner, socket, token }}:
let pkgs = import {nixpkgs} {{}}; in
pkgs.runCommand "vars-sandbox-${{builtins.substring 0 8 token}}" {{
  VARS_SOCKET = socket;
  VARS_TOKEN = token;
}} ''
  bash ${{runner}}
  mkdir -p $out
''
"""
        cmd = [
            "nix-build",
            "--no-out-link",
            "--option",
            "extra-sandbox-paths",
            f"{self.socket_path} {runner_path}",
            "--argstr",
            "runner",
            runner_path,
            "--argstr",
            "socket",
            str(self.socket_path),
            "--argstr",
            "token",
            token,
            "-E",
            expr,
        ]
        env = os.environ.copy()
        if self.nixpkgs_path:
            env["NIX_PATH"] = f"nixpkgs={self.nixpkgs_path}"
        subprocess.run(cmd, env=env, check=True)
