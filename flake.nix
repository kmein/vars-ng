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
      python = pkgs.python3.withPackages (ps: with ps; [ uv ]);
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [ python ];
      };
    };
}
