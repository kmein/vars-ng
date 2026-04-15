import pytest
from vars_ng.models import Backend


def make_file_config(name, **overrides):
    defaults = {
        "deploy": True,
        "generator": "test",
        "group": "root",
        "mode": "0400",
        "name": name,
        "owner": "root",
        "path": None,
        "secret": True,
    }
    defaults.update(overrides)
    return defaults


def make_generator_config(
    name, *, script="", files=None, dependencies=None, runtime_inputs=None
):
    return {
        "name": name,
        "dependencies": dependencies or [],
        "files": files or {},
        "prompts": {},
        "runtimeInputs": runtime_inputs or [],
        "script": script,
    }


def make_test_backend(store_path):
    config = {
        "name": "test",
        "get": f'cp "{store_path}/$1/$2" "$out"',
        "set": f'mkdir -p "{store_path}/$1" && cp "$in" "{store_path}/$1/$2"',
        "exists": f'test -f "{store_path}/$1/$2"',
        "delete": f'rm -f "{store_path}/$1/$2"',
        "list": f'test -d "{store_path}" && cd "{store_path}" && find . -type f -printf "%P\\n" | sed \'s|/| |\' || true',
        "generators": set(),
    }
    return Backend("test", config)


@pytest.fixture
def backend_and_store(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    return make_test_backend(store), store
