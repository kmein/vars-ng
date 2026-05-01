import argparse
import os
import json
import subprocess
from pathlib import Path

from .evaluator import evaluate_config
from .utils import get_execution_order, get_descendants, VarsError
from .execution import Runner
from .models import GeneratorConfig, Backend


def generator_needs_run(
    gen: GeneratorConfig, backend: Backend, rebuilt: set[str]
) -> bool:
    """Determines whether a generator needs to be run based on its dependencies and output files.

    A generator needs to be run if:
    - Any of its dependencies were rebuilt during this run (i.e., are in the `rebuilt` set).
    - Any of its output files are missing from the backend.
    """
    if any(dep in rebuilt for dep in gen.get("dependencies", [])):
        return True

    for file_config in gen.get("files", {}).values():
        if not backend.exists(gen_name=gen["name"], file_name=file_config["name"]):
            return True
    return False


def handle_generate(args: argparse.Namespace) -> None:
    eval_result = evaluate_config(args.configuration, args.nixpkgs)
    generators = eval_result.generators
    backends = eval_result.backends
    gen_to_backend = eval_result.gen_to_backend

    execution_order: list[str] = get_execution_order(generators)

    # Keep track of which generators were rebuilt during this run, so we can skip dependent generators that don't need to be re-run
    rebuilt = set()

    print("Execution order:")

    with Runner(
        generators=generators,
        gen_to_backend=gen_to_backend,
        backends=backends,
        configuration_path=args.configuration,
        nixpkgs_path=args.nixpkgs,
        sandbox=not args.no_sandbox,
        assume_yes=args.yes,
    ) as runner:
        for var_name in execution_order:
            var = generators[var_name]
            backend_name = gen_to_backend[var_name]
            backend = backends[backend_name]
            print(f"- {var_name}")

            if not generator_needs_run(var, backend, rebuilt):
                if args.dry_run:
                    print("  -> Would skip (already exists)")
                else:
                    print("  -> Skipping (already exists)")
                continue

            rebuilt.add(var_name)
            if args.dry_run:
                for file_config in var["files"].values():
                    print(
                        f"  -> Would create/update: {file_config['name']} for {var_name}"
                    )
            else:
                runner.generate(var_name, var, assume_yes=args.yes)


def handle_regenerate(args: argparse.Namespace) -> None:
    config = evaluate_config(args.configuration, args.nixpkgs)
    generators = config.generators
    gen_to_backend = config.gen_to_backend

    if args.target not in generators:
        raise VarsError(f"Target generator '{args.target}' not found in configuration.")

    to_regenerate = get_descendants(args.target, generators)
    to_regenerate.add(args.target)

    print(
        f"Regenerating {args.target} and its dependents: {', '.join(sorted(to_regenerate))}"
    )

    for gen_name in to_regenerate:
        gen = generators[gen_name]
        for file_config in gen["files"].values():
            if args.dry_run:
                print(
                    f"  -> [DRY-RUN] Would update: {file_config['name']} for {gen_name}"
                )

    if not args.dry_run:
        with Runner(
            generators=generators,
            gen_to_backend=gen_to_backend,
            backends=config.backends,
            configuration_path=args.configuration,
            nixpkgs_path=args.nixpkgs,
            sandbox=not args.no_sandbox,
            assume_yes=args.yes,
        ) as runner:
            for var_name in get_execution_order(generators):
                if var_name in to_regenerate:
                    runner.generate(var_name, generators[var_name], assume_yes=args.yes)


def handle_garbage_collect(args: argparse.Namespace) -> None:
    config = evaluate_config(args.configuration, args.nixpkgs)
    generators = config.generators
    backends = config.backends

    for backend_name, backend in backends.items():
        if not backend.config.get("list") or not backend.config.get("delete"):
            print(
                f"Skipping garbage collection for backend '{backend_name}' (missing 'list' or 'delete' script)."
            )
            continue

        try:
            lines = backend.list()
        except subprocess.CalledProcessError as e:
            print(
                f"Error running 'list' script for backend '{backend_name}': {e.stderr}"
            )
            continue

        # Ensure we have pairs of gen/file
        found_pairs = set()
        for line in lines:
            if not line:
                continue
            parts = line.strip().split()
            if len(parts) >= 2:
                found_pairs.add((parts[0], parts[1]))
            else:
                print(
                    f"Warning: ignoring malformed output from list script in backend '{backend_name}': {line}"
                )

        # Compute active pairs
        active_pairs = set()
        for gen_name in backend.config["generators"]:
            if gen_name in generators:
                for file_name in generators[gen_name]["files"]:
                    active_pairs.add((gen_name, file_name))

        stale_pairs = found_pairs - active_pairs
        if not stale_pairs:
            print(f"Backend '{backend_name}': Everything is clean.")
            continue

        for gen_name, file_name in sorted(stale_pairs):
            if args.dry_run:
                print(
                    f"  -> [DRY-RUN] Would delete from backend '{backend_name}': {gen_name}/{file_name}"
                )
            else:
                print(
                    f"  -> Deleting from backend '{backend_name}': {gen_name}/{file_name}"
                )
                try:
                    backend.delete(
                        gen_name=gen_name, file_name=file_name, assume_yes=args.yes
                    )
                except subprocess.CalledProcessError as e:
                    print(f"Error deleting {gen_name}/{file_name}: {e.stderr}")


def handle_evaluate(args: argparse.Namespace) -> None:
    data = evaluate_config(args.configuration, args.nixpkgs)

    # Check for cycles. This will raise an error if a cycle is detected.
    get_execution_order(data.generators)

    print(
        json.dumps(
            {
                "generators": data.generators,
                "gen_to_backend": data.gen_to_backend,
                "backends": {k: v.config for k, v in data.backends.items()},
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="vars-ng CLI")

    # Global arguments
    parser.add_argument(
        "--configuration",
        type=Path,
        required="VARS_CONFIG" not in os.environ,
        default=(
            Path(os.environ["VARS_CONFIG"]) if "VARS_CONFIG" in os.environ else None
        ),
        help="Path to config.nix (required unless $VARS_CONFIG is set)",
    )
    parser.add_argument(
        "--nixpkgs",
        default=os.environ.get("VARS_NIXPKGS"),
        help="Path to nixpkgs tree (default: $VARS_NIXPKGS)",
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
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically confirm all backend execution prompts (dangerous)",
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

    try:
        if args.command == "generate":
            handle_generate(args)
        elif args.command == "regenerate":
            handle_regenerate(args)
        elif args.command == "garbage-collect":
            handle_garbage_collect(args)
        elif args.command == "evaluate":
            handle_evaluate(args)
    except VarsError as e:
        print(str(e))
        exit(1)
