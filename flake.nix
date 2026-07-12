{
  description = "narrative-compiler-py / audiobook_ai development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;
        pythonPackages = python.pkgs;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python toolchain (app: narrative-compiler-py / audiobook_ai)
            pythonPackages.python
            pythonPackages.pip
            pythonPackages.uv
            pythonPackages.setuptools
            pythonPackages.wheel
            pythonPackages.openpyxl
            pythonPackages.requests
            pythonPackages.python-dotenv
            pyright
            git
            zstd
            zlib

            # Audiobook merge (MVP default: M4B)
            ffmpeg

            # System deps from Fish Speech install docs (apt: portaudio19-dev, libsox-dev, ffmpeg)
            # Used when building/running a separate fish-speech clone (Python 3.12) or native audio bindings.
            portaudio
            sox
            pkg-config
            libsndfile
            cmake

            # C++ runtime for binary wheels (e.g. PyMuPDF) under the Nix shell
            stdenv.cc.cc.lib
          ];

          # Headers for compiling pyaudio / similar against portaudio when needed outside pure Nix python pkgs
          nativeBuildInputs = with pkgs; [
            pkg-config
          ];

          shellHook = ''
            export PYTHONPATH=.:$PYTHONPATH

            export PKG_CONFIG_PATH="${pkgs.portaudio}/lib/pkgconfig:${pkgs.libsndfile}/lib/pkgconfig:${pkgs.sox}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

            # Binary wheels (numpy, scipy, soundfile, …) need these at runtime on NixOS.
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
              pkgs.zstd
              pkgs.zlib
              pkgs.libsndfile
              pkgs.stdenv.cc.cc.lib
            ]}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

            echo "Development environment ready"
          '';

          # shellHook = ''
          #   export PYTHONPATH=.:$PYTHONPATH
          #   export PKG_CONFIG_PATH="${pkgs.portaudio}/lib/pkgconfig:${pkgs.libsndfile}/lib/pkgconfig:${pkgs.sox}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
          #   export LD_LIBRARY_PATH="${pkgs.zstd}/lib:${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
          #   echo "Development environment ready for narrative-compiler-py (ffmpeg + Fish Speech system deps)"
          # '';
        };
      });
}
