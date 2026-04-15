import json
import subprocess
from pathlib import Path
from typing import Optional, Any
from .models import VarsConfig, Backend
from .utils import VarsError


def nix_instantiate(expr: str) -> Any:
    """Evaluates a nix expression using nix-instantiate and returns the result as a Python object."""
    try:
        result = subprocess.run(
            ["nix-instantiate", "--eval", "--json", "--strict", "-E", expr],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise VarsError(f"Error evaluating nix expression:\n{e.stderr}")


def evaluate_config(
    configuration_path: Path, nixpkgs_path: Optional[str] = None
) -> VarsConfig:
    """Evaluates the given config.nix file and returns the vars configuration."""
    # Note: options.nix is now adjacent to this module instead of main.py
    backend_local_nix_path = Path(__file__).parent / "backend-local.nix"
    options_nix_path = Path(__file__).parent / "options.nix"
    config_nix = configuration_path.resolve().as_posix()  # canonicalize

    nixpkgs_path = nixpkgs_path or "<nixpkgs>"

    nix_expr = f"""
let
  pkgs = import {nixpkgs_path} {{}};
  eval = pkgs.lib.evalModules {{
    modules = [
      {{ _module.args.pkgs = pkgs; }}
      {options_nix_path}
      {backend_local_nix_path}
      {config_nix}
    ];
  }};
in
{{
  generators = eval.config.vars.generators;
  backends = eval.config.vars.backends;
}}
"""

    result = nix_instantiate(nix_expr)

    # Process backends and build gen_to_backend mapping
    gen_to_backend = {}
    backend_objects = {}
    backends = result.get("backends", {})
    for backend_name, backend_config in backends.items():
        gen_keys = list(backend_config.get("generators", {}).keys())
        for gen in gen_keys:
            gen_to_backend[gen] = backend_name
        backend_config["generators"] = set(gen_keys)
        backend_objects[backend_name] = Backend(backend_name, backend_config)

    return VarsConfig(
        generators=result.get("generators", {}),
        backends=backend_objects,
        gen_to_backend=gen_to_backend,
    )
