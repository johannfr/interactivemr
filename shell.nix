{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    (python3.withPackages (ps: with ps; [
      python-gitlab
      textual
      click
      python-dotenv
      rich # For syntax highlighting, also a textual dependency
      requests
      pygments
      fuzzywuzzy
      ipython
      platformdirs
    ]))
  ];
}
