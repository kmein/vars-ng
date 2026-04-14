import argparse
import subprocess
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, TypedDict
from graphlib import TopologicalSorter

class FileConfig(TypedDict):
    deploy: bool
    generator: str
    group: str
    mode: str
    name: str
    owner: str
    path: Optional[str]
    secret: bool

class GeneratorConfig(TypedDict):
    dependencies: List[str]
    files: Dict[str, FileConfig]
    name: str
    prompts: Dict[str, Any]
    runtimeInputs: List[str]
    script: str

def nix_instantiate(expr: str) -> Any:
    try:
        result = subprocess.run(
            ["nix-instantiate", "--eval", "--json", "--strict", "-E", expr],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error evaluating nix expression:\n{e.stderr}")
        exit(1)

def evaluate_config(config_nix: str) -> Dict[str, GeneratorConfig]:
    nix_expr = f"""
let
  pkgs = import <nixpkgs> {{}};
in
(pkgs.lib.evalModules {{
  modules = [
    {{ _module.args.pkgs = pkgs; }}
    ./options.nix
    ./{config_nix}
  ];
}}).config.vars.generators
"""
    return nix_instantiate(nix_expr)

def get_sorted_generators(generators: Dict[str, GeneratorConfig]) -> List[str]:
    ts = TopologicalSorter()
    for name, gen in generators.items():
        deps = gen["dependencies"]
        ts.add(name, *deps)
    try:
        return list(ts.static_order())
    except Exception as e:
        print(f"Error: Dependency cycle detected in configuration:\n{e}")
        exit(1)

def get_file_dest_path(output_dir: str, gen_name: str, file_name: str, file_config: FileConfig) -> Path:
    visibility = "secret" if file_config["secret"] else "public"
    generator_name = file_config["generator"]
    name = file_config["name"]
    return Path(output_dir) / visibility / generator_name / name

def run_generator(gen_name: str, gen: GeneratorConfig, generators: Dict[str, GeneratorConfig], output_dir: str) -> None:
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            in_dir = temp_dir / "in"
            out_dir = temp_dir / "out"
            in_dir.mkdir()
            out_dir.mkdir()

            # Set up inputs from dependencies
            for dep_name in gen["dependencies"]:
                dep_gen = generators[dep_name]
                dep_dir = in_dir / dep_name
                dep_dir.mkdir(exist_ok=True)
                for file_name, file_config in dep_gen["files"].items():
                    src_path = get_file_dest_path(output_dir, dep_name, file_name, file_config)
                    dest_path = dep_dir / file_config["name"]
                    if src_path.exists():
                        shutil.copy2(src_path, dest_path)

            # Prepare environment
            env = os.environ.copy()
            env["in"] = str(in_dir)
            env["out"] = str(out_dir)

            # Prepare PATH with runtimeInputs
            runtime_inputs = gen["runtimeInputs"]
            bin_paths = [str(Path(p) / "bin") for p in runtime_inputs]
            if bin_paths:
                # Add existing PATH so standard tools (like bash itself, if not in runtimeInputs) are still available
                env["PATH"] = ":".join(bin_paths) + ":" + env.get("PATH", "")

            # Write and execute script
            script_content = gen["script"]
            script_path = temp_dir / "script.sh"
            script_path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\numask 077\n{script_content}")
            script_path.chmod(script_path.stat().st_mode | 0o111)

            try:
                subprocess.run([str(script_path)], env=env, check=True, cwd=str(temp_dir))
            except subprocess.CalledProcessError as e:
                print(f"Error executing script for generator {gen_name}")
                exit(1)

            # Move generated files to destination
            for file_name, file_config in gen["files"].items():
                name = file_config["name"]
                dest_path = get_file_dest_path(output_dir, gen_name, file_name, file_config)

                src_file = out_dir / name
                if src_file.exists():
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_file), str(dest_path))

                    # Set mode
                    mode_str = file_config["mode"]
                    if mode_str:
                        try:
                            dest_path.chmod(int(mode_str, 8))
                        except ValueError:
                            print(f"Warning: Invalid mode '{mode_str}' for {name}")
    finally:
        os.umask(old_umask)

def check_file_consistency(data: Dict[str, GeneratorConfig], output_dir: str) -> None:
    existing_files = []
    missing_files = []

    for gen_name, gen in data.items():
        for file_name, file_config in gen["files"].items():
            path = get_file_dest_path(output_dir, gen_name, file_name, file_config)
            if path.exists():
                existing_files.append(path)
            else:
                missing_files.append(path)

    if existing_files and missing_files:
        print("Error: Inconsistent state detected. Some generated files exist while others are missing.")
        print("\nExisting files:")
        for p in existing_files:
            print(f"  - {p}")
        print("\nMissing files:")
        for p in missing_files:
            print(f"  - {p}")
        exit(1)

def handle_generate(args: argparse.Namespace) -> None:
    generators = evaluate_config(args.config_nix)
    sorted_generators = get_sorted_generators(generators)
    check_file_consistency(generators, args.output_dir)

    print("Execution order:")
    for gen_name in sorted_generators:
        gen = generators[gen_name]
        print(f"- {gen_name}")
        if args.dry_run:
            for file_name, file_config in gen["files"].items():
                path = get_file_dest_path(args.output_dir, gen_name, file_name, file_config)
                print(f"  -> Would create/update: {path}")
        else:
            run_generator(gen_name, gen, generators, args.output_dir)

def handle_evaluate(args: argparse.Namespace) -> None:
    data = evaluate_config(args.config_nix)

    # Check for cycles
    get_sorted_generators(data)

    check_file_consistency(data, args.output_dir)
    print(json.dumps(data, indent=2))

def main() -> None:
    parser = argparse.ArgumentParser(description="vars-ng CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
    generate_parser = subparsers.add_parser("generate", help="Generate configuration")
    generate_parser.add_argument("config_nix", help="Path to config.nix")
    generate_parser.add_argument("--output-dir", default="./output", help="Directory to output generated files")
    generate_parser.add_argument("--dry-run", action="store_true", help="Print what would be done without executing")

    # evaluate subcommand
    evaluate_parser = subparsers.add_parser("evaluate", help="Evaluate configuration")
    evaluate_parser.add_argument("config_nix", help="Path to config.nix")
    evaluate_parser.add_argument("--output-dir", default="./output", help="Directory where generated files are stored")

    args = parser.parse_args()

    if args.command == "generate":
        handle_generate(args)
    elif args.command == "evaluate":
        handle_evaluate(args)

if __name__ == "__main__":
    main()
