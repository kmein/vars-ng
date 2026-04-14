{
  description = "Proof of concept for clan-independent vars";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3.withPackages (ps: with ps; [ ty ruff ]);

      vars-ng = pkgs.python3Packages.buildPythonApplication {
        pname = "vars-ng";
        version = "0.1.0";
        src = ./.;
        pyproject = true;
        build-system = [ pkgs.python3Packages.hatchling ];
        nativeCheckInputs = [ pkgs.ty pkgs.ruff ];
        
        checkPhase = ''
          runHook preCheck
          ty check .
          ruff check .
          ruff format --check .
          runHook postCheck
        '';
      };
    in
    {
      packages.${system}.default = vars-ng;

      checks.${system} = import ./tests.nix { inherit pkgs vars-ng; };

      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [ python ];
      };
    };
}
