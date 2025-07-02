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
    ]))
  ];
  shellHook = ''
    export PS1="\[\033[01;32m\](interactive-mr)\[\033[00m\] \w$ "
  '';
}
