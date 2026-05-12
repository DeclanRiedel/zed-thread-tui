{
  description = "Thin Zed terminal runner for per-worktree nix commands";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "zed-thread-runner";
            version = "0.1.0";
            src = self;

            nativeBuildInputs = [
              pkgs.makeWrapper
              pkgs.python3
            ];

            installPhase = ''
              runHook preInstall

              install -Dm755 bin/zed-thread-runner "$out/bin/zed-thread-runner"
              patchShebangs "$out/bin/zed-thread-runner"
              wrapProgram "$out/bin/zed-thread-runner" \
                --prefix PATH : ${
                  pkgs.lib.makeBinPath [
                    pkgs.bash
                    pkgs.git
                    pkgs.nix
                  ]
                }

              runHook postInstall
            '';
          };
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/zed-thread-runner";
          meta.description = "Run and rerun per-worktree commands from a thin terminal UI";
        };
      });

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          py-compile = pkgs.runCommand "zed-thread-runner-py-compile" { } ''
            ${pkgs.python3}/bin/python3 -m py_compile ${./bin/zed-thread-runner}
            touch "$out"
          '';
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.bash
              pkgs.git
              pkgs.nix
              pkgs.python3
            ];

            shellHook = ''
              echo "dev shell: use 'nix run . -- [project...]' or './bin/zed-thread-runner'"
            '';
          };
        }
      );
    };
}
