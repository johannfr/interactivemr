from hashlib import sha1
from urllib.parse import urlparse

import gitlab
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Input, Static

from ..gitlab_client import get_gitlab_instance
from .comment_dialog import CommentDialog
from .diff_view import DiffView


class InteractiveMRApp(App):
    """The main application for the interactive merge request tool."""

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("alt+right", "next_diff", "Next"),
        ("alt+left", "prev_diff", "Previous"),
        ("ctrl+l", "clear_input", "Clear command input"),
    ]

    CSS = """
    #main-container {
        height: 90%;
    }
    #command-input {
        height: 10%;
    }
    #main-container > DiffView {
        height: 1fr;
    }
    /* The main content container should fill the available space in DiffView */
    DiffView > #diff-container {
        height: 1fr;
    }
    .diff-panel {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        overflow: auto;
    }
    /* The main header for the file/counter */
    .diff-header {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1; /* Explicitly set height to 1 line */
    }
    /* The headers for the 'Old' and 'New' panes */
    .diff-header-panes {
        text-align: center;
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1; /* Explicitly set height to 1 line */
    }
    /* Align items within the main header */
    .diff-header > .filename {
        content-align: center middle;
        width: 1fr;
    }
    .diff-header > .counter {
        content-align: right middle;
        width: auto;
    }
    """

    def __init__(self, merge_request, diffs, db_connection):
        super().__init__()
        self.merge_request = merge_request
        self.diffs = diffs
        self.db_connection = db_connection
        self.current_diff_index = 0
        self.comments = {}
        self.user = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Container(id="main-container"):
            yield Static(id="status-field")
        yield Input(
            placeholder="Enter command (y, c <line> <comment>, g <diff-number>)",
            id="command-input",
        )
        yield Footer()

    def _get_user(self):
        """Gets the current user from the GitLab instance."""
        if not self.user:
            try:
                self.user = self.merge_request.manager.gitlab.user
            except gitlab.exceptions.GitlabError as e:
                self.query_one("#status-field", Static).update(
                    f"[bold red]Error getting user:[/bold red] {e}"
                )

    def _load_comments(self):
        """Loads all discussions for the merge request and stores them."""
        try:
            discussions = self.merge_request.discussions.list(all=True)
            for discussion in discussions:
                for note in discussion.attributes["notes"]:
                    if "position" in note and note["position"]:
                        pos = note["position"]
                        # We only care about comments on the new path
                        if pos["new_path"]:
                            key = (pos["new_path"], pos["new_line"])
                            if key not in self.comments:
                                self.comments[key] = []
                            self.comments[key].append(
                                {
                                    "body": note["body"],
                                    "author": note["author"]["name"],
                                }
                            )
        except gitlab.exceptions.GitlabError as e:
            self.query_one("#status-field", Static).update(
                f"[bold red]Error loading comments:[/bold red] {e}"
            )

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.theme = "gruvbox"
        self._get_user()
        self._load_comments()
        self.show_current_diff()

    def show_current_diff(self):
        """Clears the screen and displays the current diff."""
        container = self.query_one("#main-container")

        old_diff_views = self.query(DiffView)
        if old_diff_views:
            old_diff_views.remove()

        if not self.diffs:
            container.mount(Static("No diffs in this merge request."))
            return

        diff_data = self.diffs[self.current_diff_index]
        diff_view = DiffView(
            diff=diff_data,
            current_diff_index=self.current_diff_index,
            total_diffs=len(self.diffs),
            comments=self.comments,
        )
        container.mount(diff_view)

        self.query_one("#command-input", Input).value = ""
        self.query_one("#command-input").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input."""
        command_text = event.value.strip()
        self.process_command(command_text)

    def process_command(self, command: str):
        """Process the user's command."""
        parts = command.split(" ", 2)
        cmd = parts[0]
        current_diff = self.diffs[self.current_diff_index]

        if cmd == "y":
            current_diff_path = current_diff["new_path"]
            current_diff_hash = sha1(current_diff["diff"].encode("utf-8")).hexdigest()
            cursor = self.db_connection.cursor()
            cursor.execute(
                "INSERT INTO diff_hashes (path, hash) VALUES (?, ?)",
                (current_diff_path, current_diff_hash),
            )
            self.db_connection.commit()
            current_diff["approved"] = True
            self.action_next_diff()
        elif cmd == "c":
            if len(parts) < 3:
                self.query_one("#status-field", Static).update(
                    "[bold red]Error:[/bold red] 'c' command requires a line number and a comment."
                )
                return
            line_num = int(parts[1])
            comment = parts[2]
            self.post_comment(current_diff, line_num, comment)
        elif cmd == "g":
            if len(parts) < 2:
                self.query_one("#status-field", Static).update(
                    "[bold red]Error:[/bold red] 'g' command requires a diff-number."
                )
                return
            goto_diff_number = int(parts[1])
            self.action_goto_diff(goto_diff_number)
        else:
            self.query_one("#status-field", Static).update(
                f"[bold red]Unknown command:[/bold red] {cmd}"
            )

    def _reauthenticate(self):
        """Re-authenticates with GitLab and updates the merge request object."""
        try:
            # Assuming the gitlab_url can be extracted from the merge_request object
            parsed_url = urlparse(self.merge_request.web_url)
            gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

            new_gl = get_gitlab_instance(gitlab_url)

            # Re-fetch the project and merge request objects with the new instance
            project = new_gl.projects.get(self.merge_request.project_id)
            self.merge_request = project.mergerequests.get(self.merge_request.iid)

            self.query_one("#status-field", Static).update(
                "[bold green]Successfully re-authenticated.[/bold green]"
            )
        except Exception as e:
            self.query_one("#status-field", Static).update(
                f"[bold red]Re-authentication failed:[/bold red] {e}"
            )
            # Depending on the desired behavior, you might want to quit the app
            # self.exit()

    def post_comment(self, diff, line_num, comment_text):
        """Posts a comment to the GitLab merge request."""
        comment_data = {
            "body": comment_text,
            "position": {
                "base_sha": self.merge_request.diff_refs["base_sha"],
                "start_sha": self.merge_request.diff_refs["start_sha"],
                "head_sha": self.merge_request.diff_refs["head_sha"],
                "position_type": "text",
                "old_path": diff["old_path"],
                "new_path": diff["new_path"],
                "new_line": line_num,
            },
        }

        try:
            self.merge_request.discussions.create(comment_data)
            # Add the comment to our local store and refresh the view
            key = (diff["new_path"], line_num)
            if key not in self.comments:
                self.comments[key] = []
            self.comments[key].append(
                {"body": comment_text, "author": self.user.name if self.user else "You"}
            )
            self.show_current_diff()
            self.query_one("#status-field", Static).update(
                f"[green]Success:[/green] Comment posted to line {line_num}."
            )
        except gitlab.exceptions.GitlabAuthenticationError:
            self.query_one("#status-field", Static).update(
                "[bold yellow]Authentication failed. Attempting to re-authenticate...[/bold yellow]"
            )
            self._reauthenticate()
            # Retry posting the comment after re-authentication
            try:
                self.merge_request.discussions.create(comment_data)
                key = (diff["new_path"], line_num)
                if key not in self.comments:
                    self.comments[key] = []
                self.comments[key].append(
                    {
                        "body": comment_text,
                        "author": self.user.name if self.user else "You",
                    }
                )
                self.show_current_diff()
                self.query_one("#status-field", Static).update(
                    f"[green]Success:[/green] Comment posted to line {line_num} after re-authentication."
                )
            except gitlab.exceptions.GitlabError as e:
                self.query_one("#status-field", Static).update(
                    f"[bold red]Error:[/bold red] Failed to post comment after re-authentication: {e.response_code}"
                )
        except gitlab.exceptions.GitlabError as e:
            self.query_one("#status-field", Static).update(
                f"[bold red]Error:[/bold red] Failed to post comment: {e.response_code}. Note: Commenting on unchanged lines is currently not supported."
            )

    def action_next_diff(self):
        """Go to the next diff."""
        if self.current_diff_index < len(self.diffs) - 1:
            self.current_diff_index += 1
            self.show_current_diff()
            self.query_one("#status-field", Static).update("")
        else:
            self.query_one("#status-field", Static).update("All diffs reviewed.")

    def action_prev_diff(self):
        """Go to the previous diff."""
        if self.current_diff_index > 0:
            self.current_diff_index -= 1
            self.show_current_diff()
            self.query_one("#status-field", Static).update("")
        else:
            self.query_one("#status-field", Static).update(
                "You are already at the beginning."
            )

    def action_goto_diff(self, diff_number_to_go_to):
        # Adjust for zero-based indexing as internal lists are 0-indexed.
        target_index = diff_number_to_go_to - 1

        # Check if the target index is within the valid range of diffs.
        if 0 <= target_index < len(self.diffs):
            self.current_diff_index = target_index
            self.show_current_diff()
            # Clear any previous status messages.
            self.query_one("#status-field", Static).update("")
        else:
            # Display an error for an out-of-range diff number.
            self.query_one("#status-field", Static).update(
                f"[bold red]Error:[/bold red] Diff number {diff_number_to_go_to} is invalid."
            )

    def action_show_comments(self, file_path: str, line_number: int) -> None:
        """Show a dialog with comments for the given line number."""
        comments = self.comments.get((file_path, line_number), [])
        if comments:
            self.push_screen(CommentDialog(comments=comments, line_number=line_number))

    def action_clear_input(self):
        """Clear the command input-field."""
        self.query_one("#command-input", Input).value = ""
