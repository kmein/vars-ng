import pytest

from vars_ng.utils import VarsError, get_descendants, get_execution_order


class TestGetExecutionOrder:
    def test_empty(self):
        assert get_execution_order({}) == []

    def test_single_no_deps(self):
        gens = {"a": {"dependencies": []}}
        assert get_execution_order(gens) == ["a"]

    def test_two_independent(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": []},
        }
        order = get_execution_order(gens)
        assert set(order) == {"a", "b"}
        assert len(order) == 2

    def test_linear_chain(self):
        gens = {
            "a": {"dependencies": ["b"]},
            "b": {"dependencies": ["c"]},
            "c": {"dependencies": []},
        }
        order = get_execution_order(gens)
        assert order.index("c") < order.index("b") < order.index("a")

    def test_diamond(self):
        gens = {
            "a": {"dependencies": ["c"]},
            "b": {"dependencies": ["c"]},
            "c": {"dependencies": []},
        }
        order = get_execution_order(gens)
        assert order.index("c") < order.index("a")
        assert order.index("c") < order.index("b")

    def test_complex_dag(self):
        gens = {
            "a": {"dependencies": ["b", "c"]},
            "b": {"dependencies": ["d"]},
            "c": {"dependencies": ["d"]},
            "d": {"dependencies": []},
        }
        order = get_execution_order(gens)
        assert order.index("d") < order.index("b")
        assert order.index("d") < order.index("c")
        assert order.index("b") < order.index("a")
        assert order.index("c") < order.index("a")

    def test_cycle_raises(self):
        gens = {
            "a": {"dependencies": ["b"]},
            "b": {"dependencies": ["a"]},
        }
        with pytest.raises(VarsError, match="cycle"):
            get_execution_order(gens)

    def test_self_cycle_raises(self):
        gens = {"a": {"dependencies": ["a"]}}
        with pytest.raises(VarsError, match="cycle"):
            get_execution_order(gens)

    def test_three_node_cycle(self):
        gens = {
            "a": {"dependencies": ["b"]},
            "b": {"dependencies": ["c"]},
            "c": {"dependencies": ["a"]},
        }
        with pytest.raises(VarsError, match="cycle"):
            get_execution_order(gens)

    def test_preserves_all_generators(self):
        gens = {
            "x": {"dependencies": []},
            "y": {"dependencies": ["x"]},
            "z": {"dependencies": ["y"]},
        }
        order = get_execution_order(gens)
        assert set(order) == {"x", "y", "z"}


class TestGetDescendants:
    def test_no_children(self):
        gens = {"a": {"dependencies": []}}
        assert get_descendants("a", gens) == set()

    def test_single_child(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
        }
        assert get_descendants("a", gens) == {"b"}

    def test_chain(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
            "c": {"dependencies": ["b"]},
        }
        assert get_descendants("a", gens) == {"b", "c"}

    def test_diamond(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
            "c": {"dependencies": ["a"]},
            "d": {"dependencies": ["b", "c"]},
        }
        assert get_descendants("a", gens) == {"b", "c", "d"}

    def test_middle_of_chain(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
            "c": {"dependencies": ["b"]},
        }
        assert get_descendants("b", gens) == {"c"}

    def test_independent_not_included(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
            "c": {"dependencies": []},
        }
        assert get_descendants("a", gens) == {"b"}

    def test_target_not_in_generators(self):
        gens = {"a": {"dependencies": []}}
        assert get_descendants("nonexistent", gens) == set()

    def test_leaf_has_no_descendants(self):
        gens = {
            "a": {"dependencies": []},
            "b": {"dependencies": ["a"]},
        }
        assert get_descendants("b", gens) == set()


class TestVarsError:
    def test_is_exception(self):
        assert issubclass(VarsError, Exception)

    def test_message(self):
        err = VarsError("test message")
        assert str(err) == "test message"
