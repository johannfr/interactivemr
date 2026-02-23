# interactivemr

A terminal (TUI) application for interactively reviewing GitLab merge requests.
Displays side-by-side, syntax-highlighted diffs directly in your terminal, and
lets you approve changes, post inline comments, and teach the tool to
automatically recognise changes you have already reviewed.

## Features

- **Side-by-side diff view** with synchronized scrolling across old and new panes
- **Syntax highlighting** via tree-sitter (Gruvbox dark theme) for C/C++, Python,
  SQL, JSON, Markdown, Bash/shell, Dockerfile, TOML, and YAML; plain text for
  everything else
- **Approve diffs** with a single keystroke — the approval is persisted locally so
  previously-seen, identical changes are skipped on future runs
- **Post inline comments** directly to GitLab without leaving the terminal
- **Browse existing comments** — lines with comments are marked `C`; click or
  navigate to read them in an overlay
- **Jump to any diff** by number
- **OAuth2 authentication** with automatic token refresh — opens your browser once,
  then stores the token in `.env` for subsequent runs

## Requirements

The project uses [Nix](https://nixos.org/) for dependency management. All Python
packages and system tools are declared in `shell.nix`.

```bash
# Enter the dev shell (one-time setup, or automatic if direnv is installed)
nix-shell
```

If [direnv](https://direnv.net/) is installed and allowed, the shell activates
automatically whenever you `cd` into the repository.

## Authentication setup

Create a **GitLab OAuth2 application** for your GitLab instance:

1. In GitLab go to **User Settings → Applications** (or the Admin Area for a
   system-wide app).
2. Set the redirect URI to `http://localhost:7890`.
3. Grant the `api` scope.
4. Copy the **Application ID** and **Secret**.

Then create a `.env` file in the repo root (use `.env.template` as a guide):

```
GITLAB_APP_ID=<your application id>
GITLAB_APP_SECRET=<your application secret>
GITLAB_ACCESS_TOKEN=         # left blank — filled in automatically after first login
```

On first run the tool opens your browser for the OAuth flow, exchanges the code
for an access token, and writes `GITLAB_ACCESS_TOKEN` back into `.env`. Subsequent
runs reuse the saved token; the browser is only opened again if the token expires.

## Usage

```
python -m interactivemr --url <gitlab_repo_url> --mr <merge_request_number>
```

### Options

| Option | Required | Description |
|--------|----------|-------------|
| `--url` | yes | Full repository URL, e.g. `https://gitlab.com/user/repo` |
| `--mr` | yes | Merge request number |
| `--all` | no | Show all diffs, including ones already approved |

### Examples

```bash
# Review MR #42 in a project
python -m interactivemr --url https://gitlab.com/myorg/myrepo --mr 42

# Review MR #7, showing all diffs even if previously approved
python -m interactivemr --url https://gitlab.example.com/team/project --mr 7 --all
```

## Keyboard bindings

| Key | Action |
|-----|--------|
| `Alt+→` | Next diff |
| `Alt+←` | Previous diff |
| `↑` / `↓` | Scroll current diff up / down |
| `PgUp` / `PgDn` | Scroll current diff one page up / down |
| `Ctrl+L` | Clear the command input |
| `Ctrl+Q` | Quit |

## Commands

Commands are typed into the input bar at the bottom of the screen and submitted
with `Enter`.

| Command | Description |
|---------|-------------|
| `y` | Approve the current diff hunk. The SHA1 hash of the diff is stored locally; next time this exact change appears it will be skipped automatically. Moves to the next diff. |
| `c <line> <comment>` | Post an inline comment on line `<line>` of the new file. Example: `c 42 This should be a const.` |
| `g <n>` | Jump directly to diff number `<n>`. |
| `approve` | Submit a formal MR approval to GitLab (equivalent to clicking **Approve** in the web UI). |

## Approval persistence

When you approve a diff with `y`, a SHA1 hash of the raw diff text is stored in a
per-project SQLite database under your platform's user cache directory
(`~/.cache/interactivemr/` on Linux). On subsequent runs of the same MR — or any
MR that contains an identical change — that diff is silently skipped.

Use `--all` to override this and review every diff regardless of prior approvals.

## Supported languages for syntax highlighting

| Extension(s) | Language |
|---|---|
| `.c` `.cc` `.cpp` `.cxx` `.h` `.hpp` `.hxx` | C / C++ |
| `.py` | Python |
| `.sql` | SQL |
| `.json` | JSON |
| `.md` `.mdx` | Markdown |
| `.sh` `.bash` `.zsh` `.fish` | Bash / shell |
| `Dockerfile` `Dockerfile.*` | Dockerfile |
| `.toml` | TOML |
| `.yaml` `.yml` | YAML |

All other file types are displayed as plain text.

## Profiling

```bash
# Record a line-level profile (writes interactivemr.lprof)
kernprof -l -v -o interactivemr.lprof interactivemr/__main__.py --url <url> --mr <nr>

# Inspect the results
python -m line_profiler interactivemr.lprof
```
