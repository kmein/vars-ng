import argparse
import os
import json
from pathlib import Path

from .evaluator import evaluate_config
from .utils import get_execution_order, get_file_dest_path, get_descendants
from .execution import LocalRunner, SandboxRunner
from .models import GeneratorConfig


def generator_needs_run(
    gen: GeneratorConfig, output_dir: str, rebuilt: set[str]
) -> bool:
    """Determines whether a generator needs to be run based on its dependencies and output files.

    A generator needs to be run if:
    - Any of its dependencies were rebuilt during this run (i.e., are in the `rebuilt` set).
    - Any of its output files are missing from the output directory.
    """
    if any(dep in rebuilt for dep in gen["dependencies"]):
        return True

    for file_config in gen["files"].values():
        path = get_file_dest_path(output_dir, file_config)
        if not path.exists():
            return True
    return False


def handle_generate(args: argparse.Namespace) -> None:
    generators = evaluate_config(args.configuration, args.nixpkgs)
    execution_order: list[str] = get_execution_order(generators)

    # Keep track of which generators were rebuilt during this run, so we can skip dependent generators that don't need to be re-run
    rebuilt = set()

    print("Execution order:")

    # Use sandbox runner by default, but allow disabling it for testing or special environments
    runner_cls = LocalRunner if args.no_sandbox else SandboxRunner

    with runner_cls(generators, args.output_dir, args.nixpkgs) as runner:
        for var_name in execution_order:
            var = generators[var_name]
            print(f"- {var_name}")

            if not generator_needs_run(var, args.output_dir, rebuilt):
                if args.dry_run:
                    print("  -> Would skip (already exists)")
                else:
                    print("  -> Skipping (already exists)")
                continue

            rebuilt.add(var_name)
            if args.dry_run:
                for file_config in var["files"].values():
                    path = get_file_dest_path(args.output_dir, file_config)
                    print(f"  -> Would create/update: {path}")
            else:
                runner.generate(var_name, var)


def handle_regenerate(args: argparse.Namespace) -> None:
    generators = evaluate_config(args.configuration, args.nixpkgs)

    if args.target not in generators:
        print(f"Error: Target generator '{args.target}' not found in configuration.")
        exit(1)

    to_regenerate = get_descendants(args.target, generators)
    to_regenerate.add(args.target)

    print(f"Regenerating {args.target} and its dependents: {', '.join(to_regenerate)}")

    for gen_name in to_regenerate:
        gen = generators[gen_name]
        for file_config in gen["files"].values():
            path = get_file_dest_path(args.output_dir, file_config)
            if path.exists():
                if args.dry_run:
                    print(f"  -> Would delete: {path}")
                else:
                    print(f"  -> Deleting: {path}")
                    path.unlink()

    # Fall back to normal generate flow to rebuild the missing files
    handle_generate(args)


def handle_garbage_collect(args: argparse.Namespace) -> None:
    generators = evaluate_config(args.configuration, args.nixpkgs)
    output_dir = Path(args.output_dir)

    if not output_dir.exists() or not output_dir.is_dir():
        print(f"Output directory {output_dir} does not exist. Nothing to collect.")
        return

    # Collect all expected file paths
    expected_files = set()
    for gen in generators.values():
        for file_config in gen["files"].values():
            expected_files.add(
                get_file_dest_path(args.output_dir, file_config).resolve()
            )

    # Find all actual files in the output directory
    files_deleted = 0
    dirs_deleted = 0

    # Walk bottom-up so we can delete empty directories after their files are removed
    for root, dirs, files in os.walk(output_dir, topdown=False):
        current_dir = Path(root)

        # Check files
        for file_name in files:
            file_path = current_dir / file_name
            if file_path.resolve() not in expected_files:
                if args.dry_run:
                    print(f"Would delete orphaned file: {file_path}")
                else:
                    print(f"Deleting orphaned file: {file_path}")
                    file_path.unlink()
                files_deleted += 1

        # Check directories (delete if empty)
        for dir_name in dirs:
            dir_path = current_dir / dir_name
            if dir_path.exists() and not any(dir_path.iterdir()):
                if args.dry_run:
                    print(f"Would delete empty directory: {dir_path}")
                else:
                    print(f"Deleting empty directory: {dir_path}")
                    dir_path.rmdir()
                dirs_deleted += 1

    if files_deleted == 0 and dirs_deleted == 0:
        print("No orphaned files or directories found.")
    else:
        action = "Would collect" if args.dry_run else "Collected"
        print(f"{action} {files_deleted} files and {dirs_deleted} directories.")


def handle_evaluate(args: argparse.Namespace) -> None:
    data = evaluate_config(args.configuration, args.nixpkgs)

    # Check for cycles. This will raise an error if a cycle is detected.
    get_execution_order(data)

    existing_files = []
    missing_files = []

    for gen in data.values():
        for file_config in gen["files"].values():
            path = get_file_dest_path(args.output_dir, file_config)
            if path.exists():
                existing_files.append(path)
            else:
                missing_files.append(path)

    if existing_files and missing_files:
        print(
            "Note: Inconsistent state detected. Some generated files exist while others are missing."
        )
        print("You can run 'vars-ng generate' to fill in the missing files.")

    print(json.dumps(data, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="vars-ng CLI")

    # Global arguments
    parser.add_argument(
        "--configuration",
        type=Path,
        required="VARS_CONFIG" not in os.environ,
        default=Path(os.environ["VARS_CONFIG"])
        if "VARS_CONFIG" in os.environ
        else None,
        help="Path to config.nix (required unless $VARS_CONFIG is set)",
    )
    parser.add_argument(
        "--nixpkgs",
        default=os.environ.get("VARS_NIXPKGS"),
        help="Path to nixpkgs tree (default: $VARS_NIXPKGS)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("VARS_OUTPUT_DIR", "./output"),
        help="Directory to output generated files (default: ./output or $VARS_OUTPUT_DIR)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without executing",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Disable nix sandbox (useful for tests)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
    subparsers.add_parser("generate", help="Generate missing configuration")

    # regenerate subcommand
    regenerate_parser = subparsers.add_parser(
        "regenerate", help="Regenerate a specific var and its dependencies"
    )
    regenerate_parser.add_argument("target", help="Name of the var to regenerate")

    # garbage-collect subcommand
    subparsers.add_parser(
        "garbage-collect",
        help="Delete all vars from the output directory that are not declared",
    )

    # evaluate subcommand
    subparsers.add_parser("evaluate", help="Evaluate configuration")

    args = parser.parse_args()

    if args.command == "generate":
        handle_generate(args)
    elif args.command == "regenerate":
        handle_regenerate(args)
    elif args.command == "garbage-collect":
        handle_garbage_collect(args)
    elif args.command == "evaluate":
        handle_evaluate(args)
