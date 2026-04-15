from typing import Dict, List
from graphlib import TopologicalSorter
from .models import GeneratorConfig


def get_execution_order(generators: Dict[str, GeneratorConfig]) -> List[str]:
    """Returns a list of generator names sorted in topological order based on their dependencies."""
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


def get_descendants(target: str, generators: Dict[str, GeneratorConfig]) -> set[str]:
    rev_graph: Dict[str, List[str]] = {name: [] for name in generators}
    for name, gen in generators.items():
        for dep in gen["dependencies"]:
            if dep in rev_graph:
                rev_graph[dep].append(name)
            else:
                rev_graph[dep] = [name]

    descendants = set()

    def dfs(n: str) -> None:
        for child in rev_graph.get(n, []):
            if child not in descendants:
                descendants.add(child)
                dfs(child)

    dfs(target)
    return descendants
