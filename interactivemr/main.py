from urllib.parse import urlparse

import click
import gitlab
import requests

from .gitlab_client import get_gitlab_instance
from .tui.app import InteractiveMRApp


@click.command()
@click.option(
    "--url",
    required=True,
    help="The full repository URL (e.g., https://gitlab.com/user/repo).",
)
@click.option("--mr", required=True, type=int, help="The merge request number.")
def main(url, mr):
    """
    An interactive MergeRequest code review tool.
    """
    try:
        parsed_url = urlparse(url)
        gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        project_path = parsed_url.path.strip("/")

        gl = get_gitlab_instance(gitlab_url)

        project = gl.projects.get(project_path)
        merge_request = project.mergerequests.get(mr)
        changes = merge_request.changes()

        app = InteractiveMRApp(merge_request=merge_request, diffs=changes["changes"])
        app.run()

    except gitlab.exceptions.GitlabError as e:
        print(f"Error communicating with GitLab: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error during OAuth token exchange: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
