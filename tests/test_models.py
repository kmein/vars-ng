import subprocess

import pytest

from vars_ng.models import Backend, _approve, _confirm_script, _is_approved


class TestApproval:
    def test_not_approved_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        assert _is_approved("some script") is False

    def test_approve_then_check(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        _approve("some script")
        assert _is_approved("some script") is True

    def test_different_scripts_are_independent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        _approve("script one")
        assert _is_approved("script one") is True
        assert _is_approved("script two") is False

    def test_confirm_already_approved_returns(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        _approve("approved")
        _confirm_script("approved", label="TEST")

    def test_approve_creates_cache_dir(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        assert not cache.exists()
        _approve("test")
        assert (cache / "vars-ng" / "approved_scripts").is_dir()


class TestBackendExists:
    def test_true_when_file_present(self, backend_and_store):
        backend, store = backend_and_store
        (store / "gen").mkdir()
        (store / "gen" / "f").write_text("data")
        assert backend.exists(gen_name="gen", file_name="f") is True

    def test_false_when_missing(self, backend_and_store):
        backend, store = backend_and_store
        assert backend.exists(gen_name="gen", file_name="f") is False

    def test_false_when_dir_exists_but_not_file(self, backend_and_store):
        backend, store = backend_and_store
        (store / "gen").mkdir()
        assert backend.exists(gen_name="gen", file_name="f") is False


class TestBackendGet:
    def test_copies_file(self, backend_and_store, tmp_path):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("hello")

        out = tmp_path / "out"
        backend.get(gen_name="g", file_name="f", out_path=str(out), assume_yes=True)
        assert out.read_text() == "hello"

    def test_binary_content(self, backend_and_store, tmp_path):
        backend, store = backend_and_store
        data = bytes(range(256))
        (store / "g").mkdir()
        (store / "g" / "f").write_bytes(data)

        out = tmp_path / "out"
        backend.get(gen_name="g", file_name="f", out_path=str(out), assume_yes=True)
        assert out.read_bytes() == data

    def test_missing_source_raises(self, backend_and_store, tmp_path):
        backend, store = backend_and_store
        with pytest.raises(subprocess.CalledProcessError):
            backend.get(
                gen_name="no",
                file_name="no",
                out_path=str(tmp_path / "x"),
                assume_yes=True,
            )


class TestBackendSet:
    def test_stores_file(self, backend_and_store, tmp_path):
        backend, store = backend_and_store
        src = tmp_path / "input"
        src.write_text("stored")

        backend.set(gen_name="g", file_name="f", in_path=str(src), assume_yes=True)
        assert (store / "g" / "f").read_text() == "stored"

    def test_creates_parent_dirs(self, backend_and_store, tmp_path):
        backend, store = backend_and_store
        src = tmp_path / "input"
        src.write_text("data")

        assert not (store / "new_gen").exists()
        backend.set(
            gen_name="new_gen", file_name="f", in_path=str(src), assume_yes=True
        )
        assert (store / "new_gen" / "f").exists()

    def test_overwrites_existing(self, backend_and_store, tmp_path):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("old")

        src = tmp_path / "input"
        src.write_text("new")
        backend.set(gen_name="g", file_name="f", in_path=str(src), assume_yes=True)
        assert (store / "g" / "f").read_text() == "new"


class TestBackendList:
    def test_lists_files(self, backend_and_store):
        backend, store = backend_and_store
        (store / "gen1").mkdir()
        (store / "gen1" / "f1").write_text("a")
        (store / "gen2").mkdir()
        (store / "gen2" / "f2").write_text("b")

        lines = backend.list()
        pairs = {tuple(line.split()) for line in lines}
        assert ("gen1", "f1") in pairs
        assert ("gen2", "f2") in pairs

    def test_empty_store(self, backend_and_store):
        backend, store = backend_and_store
        assert backend.list() == []

    def test_no_list_script(self):
        config = {
            "name": "x",
            "get": "true",
            "set": "true",
            "exists": "true",
            "delete": None,
            "list": None,
            "generators": set(),
        }
        assert Backend("x", config).list() == []


class TestBackendDelete:
    def test_removes_file(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("bye")

        backend.delete(gen_name="g", file_name="f", assume_yes=True)
        assert not (store / "g" / "f").exists()

    def test_no_delete_script_is_noop(self):
        config = {
            "name": "x",
            "get": "true",
            "set": "true",
            "exists": "true",
            "delete": None,
            "list": None,
            "generators": set(),
        }
        Backend("x", config).delete(gen_name="g", file_name="f", assume_yes=True)

    def test_delete_nonexistent_succeeds(self, backend_and_store):
        backend, store = backend_and_store
        backend.delete(gen_name="g", file_name="f", assume_yes=True)
