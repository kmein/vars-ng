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
        machine.succeed("cd /tmp/workdir1 && vars-ng generate ${configNix}")

        out_a = machine.succeed("cat /tmp/workdir1/output/secret/a/a").strip()
        assert out_a == "a", f"Expected 'a', got '{out_a}'"
        out_b = machine.succeed("cat /tmp/workdir1/output/secret/b/b").strip()
        assert out_b == "a\nb", f"Expected 'a\\nb', got '{out_b}'"

        machine.succeed("rm /tmp/workdir1/output/secret/a/a")

        machine.succeed("cd /tmp/workdir1 && vars-ng generate ${configNix'}")

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
        machine.succeed("cd /tmp/workdir2 && vars-ng generate ${configIndependent1}")

        # Get modification times
        a_mtime1 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/a/a").strip()
        b_mtime1 = machine.succeed("stat -c %Y /tmp/workdir2/output/secret/b/b").strip()

        # Wait a second so mtimes will definitively change if touched
        machine.succeed("sleep 1")

        # Add 'c' and run generate again
        machine.succeed("cd /tmp/workdir2 && vars-ng generate ${configIndependent2}")

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
        machine.succeed("cd /tmp/workdir3 && vars-ng generate ${configIndependent2}")

        # Capture baseline file times
        a_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/a/a").strip()
        b_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/b/b").strip()
        c_mtime1 = machine.succeed("stat -c %Y /tmp/workdir3/output/secret/c/c").strip()

        machine.succeed("sleep 1")

        # Regenerate 'a'. This should delete and rebuild 'a' and 'b' (descendant), but skip 'c'
        machine.succeed("cd /tmp/workdir3 && vars-ng regenerate a ${configIndependent2}")

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

        machine.fail("vars-ng evaluate ${configCycle}")
        machine.fail("vars-ng generate ${configCycle}")

        output = machine.succeed("vars-ng evaluate ${configCycle} 2>&1 || true")
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
        machine.succeed("cd /tmp/workdir4 && vars-ng generate ${configAttrs}")

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
}
