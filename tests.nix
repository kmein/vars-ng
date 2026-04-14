{ pkgs, vars-ng, ... }:

{
  dependencyPropagationTest =
    let
      configNix = pkgs.writeText "config.nix" ''
        {
          vars.generators = {
            a = {
              files.a = { };
              script = '''
                echo a > "$out"/a
              ''';
            };
            b = {
              dependencies = [ "a" ];
              files.b = { };
              script = '''
                cat "$in"/a/a > "$out"/b
                echo b >> "$out"/b
              ''';
            };
          };
        }
      '';
      configNix' = pkgs.writeText "config.nix" ''
        {
          vars.generators = {
            a = {
              files.a = { };
              script = '''
                echo changed_a > "$out"/a
              ''';
            };
            b = {
              dependencies = [ "a" ];
              files.b = { };
              script = '''
                cat "$in"/a/a > "$out"/b
                echo b >> "$out"/b
              ''';
            };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng dependency propagation";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        
        machine.succeed("mkdir -p /tmp/workdir1")
        machine.succeed("cd /tmp/workdir1 && vars-ng --configuration ${configNix} generate")

        out_a = machine.succeed("cat /tmp/workdir1/output/secret/a/a").strip()
        assert out_a == "a", f"Expected 'a', got '{out_a}'"
        out_b = machine.succeed("cat /tmp/workdir1/output/secret/b/b").strip()
        assert out_b == "a\nb", f"Expected 'a\\nb', got '{out_b}'"

        machine.succeed("rm /tmp/workdir1/output/secret/a/a")

        machine.succeed("cd /tmp/workdir1 && vars-ng --configuration ${configNix'} generate")

        out_a2 = machine.succeed("cat /tmp/workdir1/output/secret/a/a").strip()
        assert out_a2 == "changed_a", f"Expected 'changed_a', got '{out_a2}'"

        out_b2 = machine.succeed("cat /tmp/workdir1/output/secret/b/b").strip()
        assert out_b2 == "changed_a\nb", f"Expected 'changed_a\\nb', got '{out_b2}'"
      '';
    };

  independentAdditionsTest =
    let
      configIndependent1 = pkgs.writeText "config-indep1.nix" ''
        {
          vars.generators = {
            a = { files.a = { }; script = "echo a_run > \"$out\"/a"; };
            b = { dependencies = [ "a" ]; files.b = { }; script = "echo b_run > \"$out\"/b"; };
          };
        }
      '';
      configIndependent2 = pkgs.writeText "config-indep2.nix" ''
        {
          vars.generators = {
            a = { files.a = { }; script = "echo a_run > \"$out\"/a"; };
            b = { dependencies = [ "a" ]; files.b = { }; script = "echo b_run > \"$out\"/b"; };
            c = { files.c = { }; script = "echo c_run > \"$out\"/c"; };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng independent additions";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        
        machine.succeed("mkdir -p /tmp/workdir2")
        machine.succeed("cd /tmp/workdir2 && vars-ng --configuration ${configIndependent1} generate")
        
        # Get modification times
        a_mtime1 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/a/a").strip()
        b_mtime1 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/b/b").strip()
        
        # Wait a second so mtimes will definitively change if touched
        machine.succeed("sleep 1")
        
        # Add 'c' and run generate again
        machine.succeed("cd /tmp/workdir2 && vars-ng --configuration ${configIndependent2} generate")

        # Verify a and b were skipped (mtimes unchanged)
        a_mtime2 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/a/a").strip()
        b_mtime2 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/b/b").strip()
        assert a_mtime1 == a_mtime2, "Expected a to be skipped (mtime unchanged)"
        assert b_mtime1 == b_mtime2, "Expected b to be skipped (mtime unchanged)"

        # Verify c was actually generated
        c_val = machine.succeed("cat /tmp/workdir2/output/secret/c/c").strip()
        assert c_val == "c_run", f"Expected c to be generated, got {c_val}"
      '';
    };

  targetedRegenerationTest =
    let
      configIndependent2 = pkgs.writeText "config-indep2.nix" ''
        {
          vars.generators = {
            a = { files.a = { }; script = "echo a_run > \"$out\"/a"; };
            b = { dependencies = [ "a" ]; files.b = { }; script = "echo b_run > \"$out\"/b"; };
            c = { files.c = { }; script = "echo c_run > \"$out\"/c"; };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng targeted regeneration";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        
        machine.succeed("mkdir -p /tmp/workdir3")
        machine.succeed("cd /tmp/workdir3 && vars-ng --configuration ${configIndependent2} generate")
        
        # Capture baseline file times
        a_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/a/a").strip()
        b_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/b/b").strip()
        c_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/c/c").strip()
        
        machine.succeed("sleep 1")
        
        # Regenerate 'a'. This should delete and rebuild 'a' and 'b' (descendant), but skip 'c'
        machine.succeed("cd /tmp/workdir3 && vars-ng --configuration ${configIndependent2} regenerate a")

        a_mtime2 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/a/a").strip()
        b_mtime2 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/b/b").strip()
        c_mtime2 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/c/c").strip()

        # Verify a and b were rebuilt (mtime changed)
        assert a_mtime1 != a_mtime2, "Expected a to be regenerated (mtime changed)"
        assert b_mtime1 != b_mtime2, "Expected b to be regenerated (mtime changed)"

        # Verify c was completely skipped
        assert c_mtime1 == c_mtime2, "Expected c to be skipped (mtime unchanged)"
      '';
    };

  cycleDetectionTest =
    let
      configCycle = pkgs.writeText "config-cycle.nix" ''
        {
          vars.generators = {
            a = { dependencies = [ "b" ]; files.a = { }; script = "echo a > \"$out\"/a"; };
            b = { dependencies = [ "a" ]; files.b = { }; script = "echo b > \"$out\"/b"; };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng cycle detection";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        
        machine.fail("vars-ng --configuration ${configCycle} evaluate")
        machine.fail("vars-ng --configuration ${configCycle} generate")
        
        output = machine.succeed("vars-ng --configuration ${configCycle} evaluate 2>&1 || true")
        assert "Dependency cycle detected" in output, "Expected cycle detection error"
      '';
    };

  fileAttributesTest =
    let
      configAttrs = pkgs.writeText "config-attrs.nix" ''
        { pkgs, ... }:
        {
          vars.generators = {
            ssh_key = {
              runtimeInputs = [ pkgs.openssh ];
              files.pubkey = {
                secret = false;
                mode = "0644";
              };
              files.privkey = {
                secret = true;
                mode = "0600";
              };
              script = '''
                ssh-keygen -t ed25519 -N "" -f "$out"/privkey
                mv "$out"/privkey.pub "$out"/pubkey
              ''';
            };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng file attributes";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        
        machine.succeed("mkdir -p /tmp/workdir4")
        machine.succeed("cd /tmp/workdir4 && vars-ng --configuration ${configAttrs} generate")
        
        # Check public key file attributes
        pub_mode = machine.succeed("stat -c '%a' /tmp/workdir4/output/public/ssh_key/pubkey").strip()
        assert pub_mode == "644", f"Expected public key mode 644, got {pub_mode}"

        # Check private key file attributes
        priv_mode = machine.succeed("stat -c '%a' /tmp/workdir4/output/secret/ssh_key/privkey").strip()
        assert priv_mode == "600", f"Expected private key mode 600, got {priv_mode}"

        # Verify it's a valid ED25519 public key
        pubkey_content = machine.succeed("cat /tmp/workdir4/output/public/ssh_key/pubkey").strip()
        assert pubkey_content.startswith("ssh-ed25519 "), "Generated public key doesn't look valid"
      '';
    };

  scriptFailureAndAtomicityTest =
    let
      configFailure = pkgs.writeText "config-failure.nix" ''
        {
          vars.generators = {
            fails = {
              files.partial = { };
              script = '''
                echo "im partial" > "$out"/partial
                exit 1
              ''';
            };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng script failure and atomicity";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        machine.succeed("mkdir -p /tmp/workdir5")
        
        # Command should fail
        machine.fail("cd /tmp/workdir5 && vars-ng --configuration ${configFailure} generate")
        
        # Verify the partial file never made it to the final output directory
        machine.fail("test -f /tmp/workdir5/output/secret/fails/partial")
      '';
    };

  dryRunSafetyTest =
    let
      configDryRun = pkgs.writeText "config-dry-run.nix" ''
        {
          vars.generators = {
            a = { files.a = { }; script = "echo a_run > \"$out\"/a"; };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng dry run safety";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        machine.succeed("mkdir -p /tmp/workdir6")
        
        # Execute dry runs
        machine.succeed("cd /tmp/workdir6 && vars-ng --configuration ${configDryRun} --dry-run generate")
        machine.succeed("cd /tmp/workdir6 && vars-ng --configuration ${configDryRun} --dry-run regenerate a")
        
        # Assert nothing was created
        machine.fail("test -d /tmp/workdir6/output")
      '';
    };

  multipleDependenciesTest =
    let
      configMultiDeps = pkgs.writeText "config-multi-deps.nix" ''
        {
          vars.generators = {
            a = { files.a = { }; script = "echo a_val > \"$out\"/a"; };
            b = { files.b = { }; script = "echo b_val > \"$out\"/b"; };
            c = {
              dependencies = [ "a" "b" ];
              files.c = { };
              script = '''
                cat "$in"/a/a > "$out"/c
                cat "$in"/b/b >> "$out"/c
              ''';
            };
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng multiple dependencies";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        machine.succeed("mkdir -p /tmp/workdir7")
        
        # Generate c, which pulls from both a and b
        machine.succeed("cd /tmp/workdir7 && vars-ng --configuration ${configMultiDeps} generate")
        
        # Verify c aggregated both upstream outputs successfully
        out_c = machine.succeed("cat /tmp/workdir7/output/secret/c/c").strip()
        assert out_c == "a_val\nb_val", f"Expected 'a_val\\nb_val', got '{out_c}'"
      '';
    };
}
