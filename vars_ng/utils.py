from pathlib import Path
from typing import Dict, List
from graphlib import TopologicalSorter
from .models import GeneratorConfig, FileConfig


def get_execution_order(generators: Dict[str, GeneratorConfig]) -> List[str]:
    """Returns a list of generator names sorted in topological order based on their dependencies."""
    ts = TopologicalSorter()
    for name, gen in generators.items():
        deps = gen["dependencies"]
        ts.add(name, *deps)
    try:
        return list(ts.static_order())
    except Exception as e:
        print(f"Error: Dependency cycle detected in configuration:\n{e}")
        exit(1)


def get_file_dest_path(output_dir: str, file_config: FileConfig) -> Path:
    """Determines the destination path for a generated file based on its configuration."""
    visibility = "secret" if file_config["secret"] else "public"
    generator_name = file_config["generator"]
    name = file_config["name"]
    return Path(output_dir) / visibility / generator_name / name


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
