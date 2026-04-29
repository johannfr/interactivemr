import sqlite3
import sys
from hashlib import sha1
from pathlib import Path
from urllib.parse import urlparse

# Apply monkeypatch for Textual/Rich style compatibility
try:
    from .monkeypatch import apply_patch

    apply_patch()
except ImportError:
    pass

import click
import gitlab
import platformdirs
import requests

from .gitlab_client import get_gitlab_instance
from .tui.app import InteractiveMRApp
from .tui.diff_item import DiffItem
from .tui.mr_picker_app import MRPickerApp

APPNAME = "interactivemr"


def _resolve_scope(gl: gitlab.Gitlab, project_path: str):
    """
    Try to resolve *project_path* as a project first, then as a group.

    Returns ``(scope_object, scope_type)`` where *scope_type* is either
    ``"project"`` or ``"group"``.
    """
    try:
        project = gl.projects.get(project_path)
        return project, "project"
    except gitlab.exceptions.GitlabGetError:
        pass

    try:
        group = gl.groups.get(project_path)
        return group, "group"
    except gitlab.exceptions.GitlabGetError:
        pass

    raise click.ClickException(
        f"Could not find a project or group at path '{project_path}'. "
        "Check that the URL is correct and that you have access."
    )


def _open_db_for_project(project_path: str) -> tuple[sqlite3.Connection, object]:
    """Open (or create) the SQLite diff-cache for a specific project path."""
    db_name = project_path.replace("/", "_")
    db_path = platformdirs.user_cache_path(
        appname=APPNAME, ensure_exists=True
    ) / Path(db_name + ".db")
    db_connection = sqlite3.connect(db_path)
    cursor = db_connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diff_hashes (
            id INTEGER PRIMARY KEY,
            mr INTEGER,
            path TEXT,
            hash TEXT
        )
    """)
    db_connection.commit()
    return db_connection, cursor


def _run_review(gl, project_path: str, mr_iid: int, all_diffs: bool) -> None:
    """Fetch a specific MR and launch the interactive review app."""
    click.echo(f"Opening MR !{mr_iid} in {project_path}…")

    db_connection, cursor = _open_db_for_project(project_path)

    project = gl.projects.get(project_path)
    merge_request = project.mergerequests.get(mr_iid)
    diffs = merge_request.diffs
    click.echo("Retrieving diffs.")
    diff_list = diffs.list(get_all=True)
    latest_change = diff_list[0]
    latest_diffs = diffs.get(latest_change.id)

    unseen_diffs = []
    for diff in latest_diffs.diffs:
        diff_item = DiffItem(diff_data=diff, approved=False)
        new_path = diff["new_path"]
        diff_hash = sha1(diff["diff"].encode("utf-8")).hexdigest()
        cursor.execute(
            "SELECT COUNT(*) as count from diff_hashes WHERE mr = ? AND path = ? AND hash = ?",
            (int(mr_iid), new_path, diff_hash),
        )
        (count,) = cursor.fetchone()
        if count > 0:
            if not all_diffs:
                continue
            diff_item.approved = True

        unseen_diffs.append(diff_item)

    click.echo("Processing diffs.")
    app = InteractiveMRApp(
        merge_request=merge_request, diffs=unseen_diffs, db_connection=db_connection
    )
    app.run()


@click.command()
@click.option(
    "--url",
    required=True,
    help="The full repository or group URL (e.g., https://gitlab.com/user/repo).",
)
@click.option(
    "--mr",
    required=False,
    default=None,
    type=int,
    help="The merge request number. Omit to browse open MRs interactively.",
)
@click.option(
    "--all", "all_diffs", is_flag=True, default=False, help="Don't filter diff hunks."
)
def main(url, mr, all_diffs):
    """
    An interactive MergeRequest code review tool.
    """
    try:
        parsed_url = urlparse(url)
        gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        project_path = parsed_url.path.strip("/")

        click.echo("Connecting to GitLab.")
        gl = get_gitlab_instance(gitlab_url)

        if mr is not None:
            # --- Direct mode: --mr was supplied, go straight to the review ---
            _run_review(gl, project_path, mr, all_diffs)

        else:
            # --- Picker mode: show the interactive MR list ---
            click.echo("Fetching current user.")
            gl.auth()
            current_user = gl.user

            click.echo("Resolving scope.")
            scope, scope_type = _resolve_scope(gl, project_path)

            picker = MRPickerApp(
                gl=gl,
                scope=scope,
                scope_type=scope_type,
                current_user=current_user,
            )
            result = picker.run()

            # result is the MRSelection passed to app.exit(), or None
            if result is None:
                click.echo("No MR selected. Exiting.")
                return

            _run_review(gl, result.project_path, result.mr_iid, all_diffs)

    except click.ClickException:
        raise
    except gitlab.exceptions.GitlabError as e:
        print(f"Error communicating with GitLab: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error during OAuth token exchange: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
