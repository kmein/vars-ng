{ pkgs, vars-ng, ... }:

{
  dependencyPropagationTest =
    let
      configNix = pkgs.writeText "config.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir1/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir1/output/secret/\$1 && cp \$in /tmp/workdir1/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir1/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b"] (_: { });
          };
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
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir1/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir1/output/secret/\$1 && cp \$in /tmp/workdir1/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir1/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b"] (_: { });
          };
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
        machine.succeed("cd /tmp/workdir1 && vars-ng --no-sandbox --configuration ${configNix} generate")

        out_a = machine.succeed("cat /tmp/workdir1/output/secret/a/a").strip()
        assert out_a == "a", f"Expected 'a', got '{out_a}'"
        out_b = machine.succeed("cat /tmp/workdir1/output/secret/b/b").strip()
        assert out_b == "a\nb", f"Expected 'a\\nb', got '{out_b}'"

        machine.succeed("rm /tmp/workdir1/output/secret/a/a")

        machine.succeed("cd /tmp/workdir1 && vars-ng --no-sandbox --configuration ${configNix'} generate")

        out_a2 = machine.succeed("cat /tmp/workdir1/output/secret/a/a").strip()
        assert out_a2 == "changed_a", f"Expected 'changed_a', got '{out_a2}'"

        out_b2 = machine.succeed("cat /tmp/workdir1/output/secret/b/b").strip()
        assert out_b2 == "changed_a\nb", f"Expected 'changed_a\\nb', got '{out_b2}'"
      '';
    };

  independentAdditionsTest =
    let
      configIndependent1 = pkgs.writeText "config-indep1.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir2/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir2/output/secret/\$1 && cp -f \$in /tmp/workdir2/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir2/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b"] (_: { });
          };
          vars.generators = {
            a = { files.a = { }; script = "echo a_run > \"$out\"/a"; };
            b = { dependencies = [ "a" ]; files.b = { }; script = "echo b_run > \"$out\"/b"; };
          };
        }
      '';
      configIndependent2 = pkgs.writeText "config-indep2.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir2/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir2/output/secret/\$1 && cp -f \$in /tmp/workdir2/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir2/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b" "c"] (_: { });
          };
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
        machine.succeed("cd /tmp/workdir2 && vars-ng --no-sandbox --configuration ${configIndependent1} generate")
        
        # Get modification times
        a_mtime1 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/a/a").strip()
        b_mtime1 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/b/b").strip()
        
        # Wait a second so mtimes will definitively change if touched
        machine.succeed("sleep 1")
        
        # Add 'c' and run generate again
        machine.succeed("cd /tmp/workdir2 && vars-ng --no-sandbox --configuration ${configIndependent2} generate")

        # Verify a and b were skipped (mtimes unchanged)
        a_mtime2 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/a/a").strip()
        b_mtime2 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/b/b").strip()
        assert a_mtime1 == a_mtime2, f"Expected a to be skipped (mtime unchanged), but {a_mtime1} != {a_mtime2}"
        assert b_mtime1 == b_mtime2, f"Expected b to be skipped (mtime unchanged), but {b_mtime1} != {b_mtime2}"

        # Verify c was actually generated
        c_val = machine.succeed("cat /tmp/workdir2/output/secret/c/c").strip()
        assert c_val == "c_run", f"Expected c to be generated, got {c_val}"
      '';
    };

  targetedRegenerationTest =
    let
      configIndependent2 = pkgs.writeText "config-indep2.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir3/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir3/output/secret/\$1 && cp \$in /tmp/workdir3/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir3/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b" "c"] (_: { });
          };
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
        machine.succeed("cd /tmp/workdir3 && vars-ng --no-sandbox --configuration ${configIndependent2} generate")
        
        # Capture baseline file times
        a_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/a/a").strip()
        b_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/b/b").strip()
        c_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/c/c").strip()
        
        machine.succeed("sleep 1")
        
        # Regenerate 'a'. This should delete and rebuild 'a' and 'b' (descendant), but skip 'c'
        machine.succeed("cd /tmp/workdir3 && vars-ng --no-sandbox --configuration ${configIndependent2} regenerate a")

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
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir_cycle/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir_cycle/output/secret/\$1 && cp \$in /tmp/workdir_cycle/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir_cycle/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b"] (_: { });
          };
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
        
        machine.fail("vars-ng --no-sandbox --configuration ${configCycle} evaluate")
        machine.fail("vars-ng --no-sandbox --configuration ${configCycle} generate")
        
        output = machine.succeed("vars-ng --no-sandbox --configuration ${configCycle} evaluate 2>&1 || true")
        assert "Dependency cycle detected" in output, "Expected cycle detection error"
      '';
    };

  fileAttributesTest =
    let
      configAttrs = pkgs.writeText "config-attrs.nix" ''
        { pkgs, ... }:
        {

          vars.backends.local = {
            get = "if [ \"\$2\" = \"pubkey\" ]; then cp /tmp/workdir4/output/public/\$1/\$2 \$out; else cp /tmp/workdir4/output/secret/\$1/\$2 \$out; fi";
            set = "if [ \"\$2\" = \"pubkey\" ]; then mkdir -p /tmp/workdir4/output/public/\$1 && cp \$in /tmp/workdir4/output/public/\$1/\$2 && chmod 644 /tmp/workdir4/output/public/\$1/\$2; else mkdir -p /tmp/workdir4/output/secret/\$1 && cp \$in /tmp/workdir4/output/secret/\$1/\$2 && chmod 600 /tmp/workdir4/output/secret/\$1/\$2; fi";
            exists = "if [ \"\$2\" = \"pubkey\" ]; then test -e /tmp/workdir4/output/public/\$1/\$2; else test -e /tmp/workdir4/output/secret/\$1/\$2; fi";
            generators = pkgs.lib.genAttrs ["ssh_key"] (_: { });
          };
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
        machine.succeed("cd /tmp/workdir4 && vars-ng --no-sandbox --configuration ${configAttrs} generate")
        
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
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir5/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir5/output/secret/\$1 && cp \$in /tmp/workdir5/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir5/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["fails"] (_: { });
          };
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
        machine.fail("cd /tmp/workdir5 && vars-ng --no-sandbox --configuration ${configFailure} generate")
        
        # Verify the partial file never made it to the final output directory
        machine.fail("test -f /tmp/workdir5/output/secret/fails/partial")
      '';
    };

  dryRunSafetyTest =
    let
      configDryRun = pkgs.writeText "config-dry-run.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir6/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir6/output/secret/\$1 && cp \$in /tmp/workdir6/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir6/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a"] (_: { });
          };
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
        machine.succeed("cd /tmp/workdir6 && vars-ng --no-sandbox --configuration ${configDryRun} --dry-run generate")
        machine.succeed("cd /tmp/workdir6 && vars-ng --no-sandbox --configuration ${configDryRun} --dry-run regenerate a")
        
        # Assert nothing was created
        machine.fail("test -d /tmp/workdir6/output")
      '';
    };

  multipleDependenciesTest =
    let
      configMultiDeps = pkgs.writeText "config-multi-deps.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir7/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir7/output/secret/\$1 && cp \$in /tmp/workdir7/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir7/output/secret/\$1/\$2";
            generators = pkgs.lib.genAttrs ["a" "b" "c"] (_: { });
          };
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
        machine.succeed("cd /tmp/workdir7 && vars-ng --no-sandbox --configuration ${configMultiDeps} generate")
        
        # Verify c aggregated both upstream outputs successfully
        out_c = machine.succeed("cat /tmp/workdir7/output/secret/c/c").strip()
        assert out_c == "a_val\nb_val", f"Expected 'a_val\\nb_val', got '{out_c}'"
      '';
    };

  garbageCollectTest =
    let
      configInitial = pkgs.writeText "config-initial.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir_gc/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir_gc/output/secret/\$1 && cp \$in /tmp/workdir_gc/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir_gc/output/secret/\$1/\$2";
            delete = "rm -f /tmp/workdir_gc/output/secret/\$1/\$2 && rmdir /tmp/workdir_gc/output/secret/\$1 2>/dev/null || true";
            list = "test -d /tmp/workdir_gc/output/secret && cd /tmp/workdir_gc/output/secret && find . -type f -printf '%P\\n' | sed 's|/| |'";
            generators = pkgs.lib.genAttrs ["a" "b" "c"] (_: { });
          };
          vars.generators = {
            a = { files.a = { }; script = "echo a > \"$out\"/a"; };
            b = { files.b = { }; script = "echo b > \"$out\"/b"; };
            c = { files.c = { }; script = "echo c > \"$out\"/c"; };
          };
        }
      '';
      configRemoved = pkgs.writeText "config-removed.nix" ''
        { pkgs, ... }:
        {
          vars.backends.local = {
            get = "cp /tmp/workdir_gc/output/secret/\$1/\$2 \$out";
            set = "mkdir -p /tmp/workdir_gc/output/secret/\$1 && cp \$in /tmp/workdir_gc/output/secret/\$1/\$2";
            exists = "test -e /tmp/workdir_gc/output/secret/\$1/\$2";
            delete = "rm -f /tmp/workdir_gc/output/secret/\$1/\$2 && rmdir /tmp/workdir_gc/output/secret/\$1 2>/dev/null || true";
            list = "test -d /tmp/workdir_gc/output/secret && cd /tmp/workdir_gc/output/secret && find . -type f -printf '%P\\n' | sed 's|/| |'";
            generators = pkgs.lib.genAttrs ["a"] (_: { });
          };
          vars.generators = {
            a = { files.a = { }; script = "echo a > \"$out\"/a"; };
            # b and c are removed
          };
        }
      '';
    in
    pkgs.testers.runNixOSTest {
      name = "vars-ng garbage collect";
      nodes.machine = { pkgs, ... }: {
        environment.systemPackages = [ vars-ng ];
        nix.nixPath = [ "nixpkgs=${pkgs.path}" ];
      };
      testScript = ''
        start_all()
        machine.succeed("mkdir -p /tmp/workdir_gc")
        
        # 1. Initial generation of a, b, c
        machine.succeed("cd /tmp/workdir_gc && vars-ng --no-sandbox --configuration ${configInitial} generate")
        machine.succeed("test -f /tmp/workdir_gc/output/secret/a/a")
        machine.succeed("test -f /tmp/workdir_gc/output/secret/b/b")
        machine.succeed("test -f /tmp/workdir_gc/output/secret/c/c")
        
        # Add a random manual file to output to ensure gc deletes untracked things correctly
        machine.succeed("mkdir -p /tmp/workdir_gc/output/secret/rogue")
        machine.succeed("touch /tmp/workdir_gc/output/secret/rogue/unknown")

        # 2. Switch to config where b and c are removed and garbage-collect
        machine.succeed("cd /tmp/workdir_gc && vars-ng --no-sandbox --configuration ${configRemoved} garbage-collect")
        
        # Verify a is kept, b, c, and rogue are removed
        machine.succeed("test -f /tmp/workdir_gc/output/secret/a/a")
        machine.fail("test -f /tmp/workdir_gc/output/secret/b/b")
        machine.fail("test -f /tmp/workdir_gc/output/secret/c/c")
        
        # Rogue is removed ONLY IF the list script supports returning it.
        # Given our list script enumerates all files in the output dir, it should return 'rogue/unknown'.
        # However, it might fail because it doesn't fit the 'gen_name file_name' 2-token format.
        # Let's adjust the rogue test to fit the format
        machine.succeed("mkdir -p /tmp/workdir_gc/output/secret/rogue")
        machine.succeed("touch /tmp/workdir_gc/output/secret/rogue/unknown")
        
        machine.succeed("cd /tmp/workdir_gc && vars-ng --no-sandbox --configuration ${configRemoved} garbage-collect")
        
        machine.fail("test -f /tmp/workdir_gc/output/secret/rogue/unknown")
      '';
    };
}
