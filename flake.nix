{
  description = "Proof of concept for clan-independent vars";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      perSystem = system: rec {
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3.withPackages (
          ps: with ps; [
            ty
            ruff
          ]
        );
        vars-ng = pkgs.python3Packages.buildPythonApplication {
          pname = "vars-ng";
          version = "0.1.0";
          src = ./.;
          pyproject = true;
          build-system = [ pkgs.python3Packages.hatchling ];
          nativeCheckInputs = [
            pkgs.ty
            pkgs.ruff
          ];

          checkPhase = ''
            runHook preCheck
            ruff check .
            ruff format --check .
            runHook postCheck
          '';
        };
      };
      each = forAllSystems perSystem;
    in
    {
      packages = forAllSystems (s: {
        default = each.${s}.vars-ng;
      });

      checks = forAllSystems (s: import ./tests.nix { inherit (each.${s}) pkgs vars-ng; });

      devShells = forAllSystems (s: {
        default = each.${s}.pkgs.mkShell { buildInputs = [ each.${s}.python ]; };
      });
    };
}
