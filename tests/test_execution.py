import http.client
import os
import secrets
import shutil
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from conftest import make_file_config, make_generator_config, make_test_backend
from vars_ng.execution import (
    MAX_UPLOAD_BYTES,
    TokenGrant,
    UnixSocketHttpServer,
    make_handler,
)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


def _make_daemon_env(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    backend = make_test_backend(store)

    generators = {
        "gen_a": make_generator_config(
            "gen_a",
            files={"file1": make_file_config("file1", generator="gen_a")},
        ),
        "gen_b": make_generator_config(
            "gen_b",
            dependencies=["gen_a"],
            files={"file2": make_file_config("file2", generator="gen_b")},
        ),
    }

    gen_to_backend = {"gen_a": "test", "gen_b": "test"}
    backends = {"test": backend}

    return store, generators, gen_to_backend, backends


@pytest.fixture
def daemon(tmp_path):
    store, generators, gen_to_backend, backends = _make_daemon_env(tmp_path)

    tokens: dict[str, TokenGrant] = {}
    tokens_lock = threading.Lock()

    socket_dir = Path(tempfile.mkdtemp(prefix="vt-", dir="/tmp"))
    socket_path = socket_dir / "s.sock"

    server = UnixSocketHttpServer(
        str(socket_path),
        make_handler(generators, gen_to_backend, backends, tokens, tokens_lock, True),
    )
    os.chmod(str(socket_path), 0o666)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield {
        "socket_path": str(socket_path),
        "store": store,
        "tokens": tokens,
        "tokens_lock": tokens_lock,
    }

    server.shutdown()
    server.server_close()
    shutil.rmtree(socket_dir, ignore_errors=True)


def _mint(daemon, generator, reads=None, writes=None):
    token = secrets.token_urlsafe(32)
    grant = TokenGrant(
        generator=generator,
        reads=reads or set(),
        writes=writes or set(),
    )
    with daemon["tokens_lock"]:
        daemon["tokens"][token] = grant
    return token


class TestTokenGrant:
    def test_defaults(self):
        g = TokenGrant(generator="x")
        assert g.reads == set()
        assert g.writes == set()
        assert g.generator == "x"

    def test_populated(self):
        g = TokenGrant(
            generator="x",
            reads={("a", "f1")},
            writes={("x", "f2")},
        )
        assert ("a", "f1") in g.reads
        assert ("x", "f2") in g.writes


class TestHttpDaemon:
    def test_no_auth_returns_401(self, daemon):
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request("GET", "/gen_a/file1")
        assert conn.getresponse().status == 401
        conn.close()

    def test_invalid_token_returns_403(self, daemon):
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request("GET", "/gen_a/file1", headers={"Authorization": "Bearer bogus"})
        assert conn.getresponse().status == 403
        conn.close()

    def test_unauthorized_read_returns_403(self, daemon):
        token = _mint(daemon, "gen_a", reads=set())
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "GET", "/gen_a/file1", headers={"Authorization": f"Bearer {token}"}
        )
        assert conn.getresponse().status == 403
        conn.close()

    def test_authorized_get(self, daemon):
        (daemon["store"] / "gen_a").mkdir()
        (daemon["store"] / "gen_a" / "file1").write_text("hello world")

        token = _mint(daemon, "gen_a", reads={("gen_a", "file1")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "GET", "/gen_a/file1", headers={"Authorization": f"Bearer {token}"}
        )
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"hello world"
        conn.close()

    def test_get_binary_content(self, daemon):
        data = bytes(range(256))
        (daemon["store"] / "gen_a").mkdir(exist_ok=True)
        (daemon["store"] / "gen_a" / "file1").write_bytes(data)

        token = _mint(daemon, "gen_a", reads={("gen_a", "file1")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "GET", "/gen_a/file1", headers={"Authorization": f"Bearer {token}"}
        )
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == data
        conn.close()

    def test_authorized_post(self, daemon):
        token = _mint(daemon, "gen_b", writes={("gen_b", "file2")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "POST",
            "/gen_b/file2",
            body=b"posted data",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert conn.getresponse().status == 200
        assert (daemon["store"] / "gen_b" / "file2").read_bytes() == b"posted data"
        conn.close()

    def test_unauthorized_write_returns_403(self, daemon):
        token = _mint(daemon, "gen_b", writes=set())
        conn = UnixHTTPConnection(daemon["socket_path"])
        try:
            conn.request(
                "POST",
                "/gen_b/file2",
                body=b"data",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert conn.getresponse().status == 403
        except BrokenPipeError:
            pass  # Server rejected before client finished sending
        finally:
            conn.close()

    def test_bad_path_single_segment(self, daemon):
        token = _mint(daemon, "gen_a", reads={("gen_a", "file1")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request("GET", "/gen_a", headers={"Authorization": f"Bearer {token}"})
        assert conn.getresponse().status == 400
        conn.close()

    def test_bad_path_three_segments(self, daemon):
        token = _mint(daemon, "gen_a", reads={("gen_a", "file1")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "GET", "/gen_a/file1/extra", headers={"Authorization": f"Bearer {token}"}
        )
        assert conn.getresponse().status == 400
        conn.close()

    def test_nonexistent_generator_returns_404(self, daemon):
        token = _mint(daemon, "nosuch", reads={("nosuch", "f")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request("GET", "/nosuch/f", headers={"Authorization": f"Bearer {token}"})
        assert conn.getresponse().status == 404
        conn.close()

    def test_nonexistent_file_returns_404(self, daemon):
        token = _mint(daemon, "gen_a", reads={("gen_a", "nosuch")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "GET", "/gen_a/nosuch", headers={"Authorization": f"Bearer {token}"}
        )
        assert conn.getresponse().status == 404
        conn.close()

    def test_post_too_large_returns_413(self, daemon):
        token = _mint(daemon, "gen_b", writes={("gen_b", "file2")})
        conn = UnixHTTPConnection(daemon["socket_path"])
        try:
            conn.putrequest("POST", "/gen_b/file2")
            conn.putheader("Authorization", f"Bearer {token}")
            conn.putheader("Content-Length", str(MAX_UPLOAD_BYTES + 1))
            conn.endheaders(b"x")
            assert conn.getresponse().status == 413
        except BrokenPipeError:
            pass  # Server closed connection before reading oversized body
        finally:
            conn.close()

    def test_post_then_get_roundtrip(self, daemon):
        token = _mint(
            daemon,
            "gen_a",
            reads={("gen_a", "file1")},
            writes={("gen_a", "file1")},
        )

        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "POST",
            "/gen_a/file1",
            body=b"roundtrip",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert conn.getresponse().status == 200
        conn.close()

        conn = UnixHTTPConnection(daemon["socket_path"])
        conn.request(
            "GET", "/gen_a/file1", headers={"Authorization": f"Bearer {token}"}
        )
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"roundtrip"
        conn.close()
