from typing import Dict, List, Set
from graphlib import TopologicalSorter
from .models import GeneratorConfig


def validate_dependencies(generators: Dict[str, GeneratorConfig]) -> None:
    """Validates that all dependencies declared by generators actually exist as generators."""
    generator_names = set(generators.keys())
    missing_dependencies: Set[str] = set()

    for name, gen in generators.items():
        for dep in gen["dependencies"]:
            if dep not in generator_names:
                missing_dependencies.add(dep)

    if missing_dependencies:
        missing_list = ", ".join(sorted(missing_dependencies))
        raise VarsError(
            f"The following dependencies are declared but not defined as generators: {missing_list}"
        )


def get_execution_order(generators: Dict[str, GeneratorConfig]) -> List[str]:
    """Returns a list of generator names sorted in topological order based on their dependencies."""
    validate_dependencies(generators)
    ts = TopologicalSorter()
    for name, gen in generators.items():
        deps = gen["dependencies"]
        ts.add(name, *deps)
    try:
        return list(ts.static_order())
    except Exception as e:
        raise VarsError(f"Dependency cycle detected in configuration:\n{e}")


class VarsError(Exception):
    """Base exception for vars-ng errors."""

    pass


def _dfs_traversal(start: str, get_neighbors: callable) -> set[str]:
    """Generic DFS traversal helper.

    Args:
        start: Starting node
        get_neighbors: Function that takes a node and returns its neighbors

    Returns:
        Set of all reachable nodes
    """
    visited = set()

    def dfs(n: str) -> None:
        for neighbor in get_neighbors(n):
            if neighbor not in visited:
                visited.add(neighbor)
                dfs(neighbor)

    dfs(start)
    return visited


def get_descendants(target: str, generators: Dict[str, GeneratorConfig]) -> set[str]:
    """Returns all generators that depend on the target, transitively."""
    # Build reverse graph: dependency -> [generators that depend on it]
    rev_graph: Dict[str, List[str]] = {name: [] for name in generators}
    for name, gen in generators.items():
        for dep in gen["dependencies"]:
            if dep in rev_graph:
                rev_graph[dep].append(name)
            else:
                rev_graph[dep] = [name]

    def get_children(n: str) -> List[str]:
        return rev_graph.get(n, [])

    return _dfs_traversal(target, get_children)


def get_ancestors(target: str, generators: Dict[str, GeneratorConfig]) -> set[str]:
    """Returns all generators that the target depends on, transitively."""

    def get_dependencies(n: str) -> List[str]:
        if n not in generators:
            return []
        return generators[n]["dependencies"]

    return _dfs_traversal(target, get_dependencies)
