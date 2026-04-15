import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, Any
from .models import GeneratorConfig


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
        print(f"Error evaluating nix expression:\n{e.stderr}")
        exit(1)


def evaluate_config(
    configuration_path: Path, nixpkgs_path: Optional[str] = None
) -> "VarsConfig":
    """Evaluates the given config.nix file and returns the vars configuration."""
    # Note: options.nix is now adjacent to this module instead of main.py
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
      {config_nix}
    ];
  }};
in
{{
  generators = eval.config.vars.generators;
  backends = eval.config.vars.backends;
}}
"""
    from .models import VarsConfig
    
    result = nix_instantiate(nix_expr)
    # Convert generators to a set for each backend
    for backend in result.get("backends", {}).values():
        backend["generators"] = set(backend.get("generators", {}).keys())
    return result
