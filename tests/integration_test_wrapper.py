#!/usr/bin/env python3

"""
Generic integration test wrapper for vars-ng.

This wrapper sets up a minimal Nix environment suitable for running
integration tests inside a nix-build context. It's designed to be
used with pkgs.runCommand for lightweight integration testing.

Based on the settings used by a competent developer for vars-ng testing.
"""

import os
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
import json


class IntegrationTestEnvironment:
    """Context manager for setting up a Nix integration test environment."""

    def __init__(self, nixpkgs_path: Optional[str] = None):
        self.nixpkgs_path = nixpkgs_path
        self.temp_dir = None
        self.original_env = {}

    def __enter__(self):
        """Set up the test environment."""
        # Create temporary directory for the test environment
        self.temp_dir = tempfile.mkdtemp(prefix="vars-ng-test-")

        # Save original environment variables that we'll modify
        self.original_env = {
            "NIX_REMOTE": os.environ.get("NIX_REMOTE"),
            "NIX_CONFIG": os.environ.get("NIX_CONFIG"),
            "HOME": os.environ.get("HOME"),
            "NIX_STATE_DIR": os.environ.get("NIX_STATE_DIR"),
            "NIX_CONF_DIR": os.environ.get("NIX_CONF_DIR"),
            "IN_NIX_SANDBOX": os.environ.get("IN_NIX_SANDBOX"),
            "CLAN_TEST_STORE": os.environ.get("CLAN_TEST_STORE"),
            "LOCK_NIX": os.environ.get("LOCK_NIX"),
        }

        # Remove NIX_REMOTE if present (we don't have any nix daemon running)
        if "NIX_REMOTE" in os.environ:
            del os.environ["NIX_REMOTE"]

        # Set NIX_CONFIG globally to disable substituters for speed
        os.environ["NIX_CONFIG"] = "substituters = \ntrusted-public-keys = "

        # Set up environment variables for test environment
        os.environ["HOME"] = str(self.temp_dir)
        os.environ["NIX_STATE_DIR"] = f"{self.temp_dir}/nix"
        os.environ["NIX_CONF_DIR"] = f"{self.temp_dir}/etc"
        os.environ["IN_NIX_SANDBOX"] = "1"
        os.environ["CLAN_TEST_STORE"] = f"{self.temp_dir}/store"
        os.environ["LOCK_NIX"] = f"{self.temp_dir}/nix_lock"

        # Create necessary directories
        Path(f"{self.temp_dir}/nix").mkdir(parents=True, exist_ok=True)
        Path(f"{self.temp_dir}/etc").mkdir(parents=True, exist_ok=True)
        Path(f"{self.temp_dir}/store").mkdir(parents=True, exist_ok=True)
        Path(f"{self.temp_dir}/store/nix/store").mkdir(parents=True, exist_ok=True)
        Path(f"{self.temp_dir}/store/nix/var/nix/gcroots").mkdir(
            parents=True, exist_ok=True
        )

        # If nixpkgs path is provided, set it up
        if self.nixpkgs_path:
            os.environ["NIX_PATH"] = f"nixpkgs={self.nixpkgs_path}"

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up the test environment."""
        # Restore original environment variables
        for var, value in self.original_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value

        # Clean up temporary directory
        if self.temp_dir and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def run_vars_ng_command(
    args: List[str],
    config_content: str,
    nixpkgs_path: Optional[str] = None,
    expect_failure: bool = False,
) -> Dict[str, Any]:
    """
    Run a vars-ng command with a temporary configuration.

    Args:
        args: List of command line arguments (e.g., ['evaluate'])
        config_content: Nix configuration content as string
        nixpkgs_path: Optional path to nixpkgs
        expect_failure: Whether to expect the command to fail

    Returns:
        Dictionary with 'success', 'returncode', 'stdout', 'stderr', and 'output' (parsed JSON if applicable)
    """
    result = {
        "success": False,
        "returncode": -1,
        "stdout": "",
        "stderr": "",
        "output": None,
    }

    with IntegrationTestEnvironment(nixpkgs_path=nixpkgs_path):
        # Create temporary config file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".nix", delete=False
        ) as config_file:
            config_file.write(config_content)
            config_path = config_file.name

        try:
            # Build the command
            cmd = ["python", "-m", "vars_ng"] + args

            # Set VARS_CONFIG environment variable instead of command line arg
            env = os.environ.copy()
            env["PYTHONPATH"] = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            env["VARS_CONFIG"] = config_path

            # Run the command
            # Set PYTHONPATH to include the vars_ng module
            env = os.environ.copy()
            env["PYTHONPATH"] = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            env["VARS_CONFIG"] = config_path

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=env,
            )

            result["returncode"] = process.returncode
            result["stdout"] = process.stdout
            result["stderr"] = process.stderr

            # Try to parse JSON output if applicable
            if process.stdout.strip() and (
                args[0] == "evaluate" or "--dry-run" in args
            ):
                try:
                    result["output"] = json.loads(process.stdout)
                except json.JSONDecodeError:
                    result["output"] = process.stdout

            # Check success/failure
            if expect_failure:
                result["success"] = process.returncode != 0
            else:
                result["success"] = process.returncode == 0

        finally:
            # Clean up config file
            os.unlink(config_path)

    return result


def test_dependency_validation():
    """Test that dependency validation works correctly."""
    print("Testing dependency validation...")

    # Test 1: Valid configuration should succeed
    valid_config = """
    {
      generators = {
        "base" = {
          dependencies = [ ];
          files."base.txt" = { deploy = true; generator = "base"; group = "root"; mode = "0644"; name = "base.txt"; owner = "root"; path = null; secret = false; };
          prompts = { };
          runtimeInputs = [ ];
          script = "echo 'base' > $out/base.txt";
        };
        "derived" = {
          dependencies = [ "base" ];
          files."derived.txt" = { deploy = true; generator = "derived"; group = "root"; mode = "0644"; name = "derived.txt"; owner = "root"; path = null; secret = false; };
          prompts = { };
          runtimeInputs = [ ];
          script = "cp $in/base/base.txt $out/derived.txt";
        };
      };
      
      backends."test" = {
        name = "test";
        get = "echo 'get: $1 $2' > $out";
        set = "echo 'set: $1 $2' > /dev/null; cp $in $out";
        exists = "echo 'exists: $1 $2'; exit 1";
        list = "echo ''";
        delete = null;
        generators = [ "base" "derived" ];
      };
      
      genToBackend = { "base" = "test"; "derived" = "test"; };
    }
    """

    result = run_vars_ng_command(["evaluate"], valid_config)
    if result["success"]:
        print("✓ Valid configuration passed evaluation")
    else:
        print(f"✗ Valid configuration failed: {result['stderr']}")
        return False

    # Test 2: Invalid configuration should fail
    invalid_config = """
    {
      generators = {
        "derived" = {
          dependencies = [ "nonexistent" ];
          files."derived.txt" = { deploy = true; generator = "derived"; group = "root"; mode = "0644"; name = "derived.txt"; owner = "root"; path = null; secret = false; };
          prompts = { };
          runtimeInputs = [ ];
          script = "echo 'derived' > $out/derived.txt";
        };
      };
      
      backends."test" = {
        name = "test";
        get = "echo 'get: $1 $2' > $out";
        set = "echo 'set: $1 $2' > /dev/null; cp $in $out";
        exists = "echo 'exists: $1 $2'; exit 1";
        list = "echo ''";
        delete = null;
        generators = [ "derived" ];
      };
      
      genToBackend = { "derived" = "test"; };
    }
    """

    result = run_vars_ng_command(["evaluate"], invalid_config, expect_failure=True)
    if result["success"] and "nonexistent" in result["stderr"]:
        print("✓ Invalid configuration correctly detected missing dependency")
    else:
        print(f"✗ Invalid configuration test failed: {result['stderr']}")
        return False

    return True


if __name__ == "__main__":
    print("Running vars-ng integration tests...")
    print("=" * 50)

    success = True

    # Run dependency validation test
    if not test_dependency_validation():
        success = False

    print("=" * 50)
    if success:
        print("✓ All integration tests passed!")
        exit(0)
    else:
        print("✗ Some integration tests failed!")
        exit(1)
