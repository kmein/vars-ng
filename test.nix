{ pkgs, vars-ng, ... }:

pkgs.testers.runNixOSTest {
  name = "vars-ng-test";

  containers.machine = { pkgs, ... }: {
    environment.systemPackages = [ vars-ng ];
  };

  testScript = ''
    start_all()
    machine.succeed("vars-ng --help")
  '';
}
