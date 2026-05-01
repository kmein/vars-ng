import json
import subprocess
from pathlib import Path
from typing import Optional, Any
from .models import VarsConfig, Backend
from .utils import VarsError


def _module_set(configuration_path: Path, nixpkgs_path: Optional[str]) -> str:
    """Builds the shared `let pkgs = ...; eval = lib.evalModules { modules = [...]; }; in` preamble."""
    backend_local = Path(__file__).parent / "backend-local.nix"
    backend_age = Path(__file__).parent / "backend-age.nix"
    options = Path(__file__).parent / "options.nix"
    config = configuration_path.resolve().as_posix()
    nixpkgs = nixpkgs_path or "<nixpkgs>"
    return f"""
let
  pkgs = import {nixpkgs} {{}};
  eval = pkgs.lib.evalModules {{
    modules = [
      {{ _module.args.pkgs = pkgs; }}
      {options}
      {backend_local}
      {backend_age}
      {config}
    ];
  }};
in
"""


def evaluate_config(
    configuration_path: Path, nixpkgs_path: Optional[str] = None
) -> VarsConfig:
    """Evaluates the given config.nix and returns metadata for all generators."""
    expr = (
        _module_set(configuration_path, nixpkgs_path)
        + """
{
  generators = builtins.mapAttrs (_: g: {
    inherit (g) name dependencies prompts;
    files = builtins.mapAttrs (_: f: {
      inherit (f) deploy generator group mode name owner path secret;
    }) g.files;
  }) eval.config.vars.generators;
  backends = eval.config.vars.backends;
}
"""
    )

    try:
        result = subprocess.run(
            ["nix-instantiate", "--eval", "--json", "--strict", "-E", expr],
            capture_output=True,
            text=True,
            check=True,
        )
        data: Any = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise VarsError(f"Error evaluating nix expression:\n{e.stderr}")

    gen_to_backend: dict[str, str] = {}
    backend_objects: dict[str, Backend] = {}
    for backend_name, backend_config in data.get("backends", {}).items():
        gen_keys = list(backend_config.get("generators", {}).keys())
        for gen in gen_keys:
            gen_to_backend[gen] = backend_name
        backend_config["generators"] = set(gen_keys)
        backend_objects[backend_name] = Backend(backend_name, backend_config)

    return VarsConfig(
        generators=data.get("generators", {}),
        backends=backend_objects,
        gen_to_backend=gen_to_backend,
    )


def runner_expr(
    configuration_path: Path, nixpkgs_path: Optional[str], var_name: str
) -> str:
    """Builds a nix expression that resolves to a single generator's runner derivation."""
    return (
        _module_set(configuration_path, nixpkgs_path)
        + f"""
eval.config.vars.generators."{var_name}".runner
"""
    )
