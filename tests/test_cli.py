from conftest import make_file_config, make_generator_config
from vars_ng.cli import generator_needs_run


class TestGeneratorNeedsRun:
    def test_all_exist_no_deps_rebuilt(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("ok")

        gen = make_generator_config(
            "g", files={"f": make_file_config("f", generator="g")}
        )
        assert generator_needs_run(gen, backend, rebuilt=set()) is False

    def test_dep_rebuilt(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("ok")

        gen = make_generator_config(
            "g",
            dependencies=["dep"],
            files={"f": make_file_config("f", generator="g")},
        )
        assert generator_needs_run(gen, backend, rebuilt={"dep"}) is True

    def test_file_missing(self, backend_and_store):
        backend, store = backend_and_store
        gen = make_generator_config(
            "g", files={"f": make_file_config("f", generator="g")}
        )
        assert generator_needs_run(gen, backend, rebuilt=set()) is True

    def test_multiple_files_one_missing(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f1").write_text("ok")
        # f2 is missing

        gen = make_generator_config(
            "g",
            files={
                "f1": make_file_config("f1", generator="g"),
                "f2": make_file_config("f2", generator="g"),
            },
        )
        assert generator_needs_run(gen, backend, rebuilt=set()) is True

    def test_no_files_no_deps(self, backend_and_store):
        backend, store = backend_and_store
        gen = make_generator_config("g")
        assert generator_needs_run(gen, backend, rebuilt=set()) is False

    def test_multiple_deps_one_rebuilt(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("ok")

        gen = make_generator_config(
            "g",
            dependencies=["a", "b"],
            files={"f": make_file_config("f", generator="g")},
        )
        assert generator_needs_run(gen, backend, rebuilt={"b"}) is True

    def test_multiple_deps_none_rebuilt(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f").write_text("ok")

        gen = make_generator_config(
            "g",
            dependencies=["a", "b"],
            files={"f": make_file_config("f", generator="g")},
        )
        assert generator_needs_run(gen, backend, rebuilt=set()) is False

    def test_all_files_exist_multiple(self, backend_and_store):
        backend, store = backend_and_store
        (store / "g").mkdir()
        (store / "g" / "f1").write_text("ok")
        (store / "g" / "f2").write_text("ok")

        gen = make_generator_config(
            "g",
            files={
                "f1": make_file_config("f1", generator="g"),
                "f2": make_file_config("f2", generator="g"),
            },
        )
        assert generator_needs_run(gen, backend, rebuilt=set()) is False
