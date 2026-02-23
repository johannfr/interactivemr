{pkgs ? import <nixpkgs> {}}:
pkgs.mkShell {
  buildInputs = with pkgs; [
    tree-sitter
    (python3.withPackages (ps:
      with ps; [
        python-gitlab
        textual
        click
        python-dotenv
        requests
        fuzzywuzzy
        ipython
        platformdirs
        tree-sitter
        (line-profiler.overridePythonAttrs (oldAttrs: {
          doCheck = false;
          doInstallCheck = false;
        }))
      ]))
    # Tree-sitter grammars (names may vary by nixpkgs version)
    tree-sitter-grammars.tree-sitter-cpp
    tree-sitter-grammars.tree-sitter-python
    tree-sitter-grammars.tree-sitter-sql
    tree-sitter-grammars.tree-sitter-json
    tree-sitter-grammars.tree-sitter-markdown
    tree-sitter-grammars.tree-sitter-bash
    tree-sitter-grammars.tree-sitter-dockerfile
    tree-sitter-grammars.tree-sitter-toml
    tree-sitter-grammars.tree-sitter-yaml
  ];
}
