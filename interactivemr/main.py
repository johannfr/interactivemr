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

APPNAME = "interactivemr"


@click.command()
@click.option(
    "--url",
    required=True,
    help="The full repository URL (e.g., https://gitlab.com/user/repo).",
)
@click.option("--mr", required=True, type=int, help="The merge request number.")
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
        db_name = project_path.replace("/", "_")

        # First we'll open/create our database
        db_path = platformdirs.user_cache_path(
            appname=APPNAME, ensure_exists=True
        ) / Path(db_name + ".db")
        db_connection = sqlite3.connect(db_path)

        # Create our cache-table
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

        click.echo("Connecting to Gitlab.")
        gl = get_gitlab_instance(gitlab_url)

        project = gl.projects.get(project_path)
        merge_request = project.mergerequests.get(mr)
        diffs = merge_request.diffs
        click.echo("Retrieving diffs.")
        diff_list = diffs.list(get_all=True)
        latest_change = diff_list[0]  # Hopefully they keep the same order.
        latest_diffs = diffs.get(latest_change.id)

        unseen_diffs = []
        for diff in latest_diffs.diffs:
            # Why only SHA1 you ask? Because it's plenty strong enough for this purpose.
            diff_item = DiffItem(diff_data=diff, approved=False)
            new_path = diff["new_path"]
            diff_hash = sha1(diff["diff"].encode("utf-8")).hexdigest()
            cursor.execute(
                "SELECT COUNT(*) as count from diff_hashes WHERE mr = ? AND path = ? AND hash = ?",
                (int(mr), new_path, diff_hash),
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

    except gitlab.exceptions.GitlabError as e:
        print(f"Error communicating with GitLab: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error during OAuth token exchange: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
