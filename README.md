# vars-ng

`vars-ng` is a proof-of-concept next-generation configuration and secret generator, designed to be independent of specific frameworks (like `clan-core`), utilizing Nix for configuration evaluation and isolated execution.

## Features

- **Nix-Driven Configuration**: Generators are defined in Nix using a robust module system (`options.nix`), ensuring type safety and reusability.
- **Dependency Graph**: Generators can define dependencies on one another. `vars-ng` automatically resolves the execution order using topological sorting.
- **Isolated Execution**: By default, generator scripts run in a strict, isolated Nix sandbox (`pkgs.runCommand`). Dependencies are fetched and outputs are posted back to the host via a background Unix socket HTTP server.
- **Local Execution Fallback**: A `--no-sandbox` option is available to run generators directly on the host using temporary directories, useful for testing or environments where Nix sandboxing is unavailable.
- **State Management**: Only runs what is missing or whose dependencies have been updated. Includes commands for targeted regeneration and garbage collection of orphaned files.

## Usage

You can run `vars-ng` directly using Nix flakes:

```bash
nix run . -- --configuration path/to/config.nix --output-dir ./output generate
```

### Commands

* `generate`: Evaluates the configuration and runs any generators that have missing outputs or updated dependencies.
* `regenerate <target>`: Forces regeneration of a specific generator and any other generators that depend on it.
* `garbage-collect`: Scans the output directory and removes any files or empty directories that are no longer declared in the current configuration.
* `evaluate`: Evaluates the Nix configuration, checks for dependency cycles, and prints a JSON representation of the vars configuration without executing any generators.

### Options

* `--configuration`: Path to the `config.nix` file (or set via `VARS_CONFIG` environment variable).
* `--output-dir`: Directory to output generated files (defaults to `./output` or `VARS_OUTPUT_DIR`).
* `--nixpkgs`: Path to the `nixpkgs` tree (defaults to `<nixpkgs>` or `VARS_NIXPKGS`).
* `--dry-run`: Prints what actions would be taken without modifying the filesystem or executing scripts.
* `--no-sandbox`: Disables the Nix sandbox, running bash scripts directly on the host machine.

## Architecture

* **Models** (`vars_ng/models.py`): Typed dictionaries representing the Nix module structure.
* **Evaluator** (`vars_ng/evaluator.py`): Uses `nix-instantiate` to evaluate `config.nix` against the defined `options.nix`.
* **Execution Engine** (`vars_ng/execution.py`):
  * `SandboxRunner`: Sets up a Unix socket HTTP server, injects it into `nix-build` via `extra-sandbox-paths`, and provides sandboxed curl access to fetch/put files.
  * `LocalRunner`: Simulates the sandbox on the host using standard temporary directories.
* **CLI** (`vars_ng/cli.py`): Command-line argument parsing and orchestration.
