from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Input, Static
import gitlab
from urllib.parse import urlparse

from ..ai import GeminiAI
from .diff_view import DiffView
from ..gitlab_client import get_gitlab_instance


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

    def __init__(self, merge_request, diffs):
        super().__init__()
        self.merge_request = merge_request
        self.diffs = diffs
        self.current_diff_index = 0
        self.ai = GeminiAI()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Container(id="main-container"):
            yield Static(id="ai-suggestion")
        yield Input(
            placeholder="Enter command (y, yl, c <line> <comment>, cl <line> <comment>)",
            id="command-input",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
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
        )
        container.mount(diff_view)

        suggestion = self.ai.find_similar_chunk(diff_data["diff"])
        suggestion_widget = self.query_one("#ai-suggestion", Static)
        if suggestion:
            if suggestion["comment"]:
                suggestion_widget.update(
                    f"[bold green]AI Suggestion:[/bold green] Previously learned comment: '{suggestion['comment']}'"
                )
            else:
                suggestion_widget.update(
                    "[bold green]AI Suggestion:[/bold green] This change looks similar to one you've approved before."
                )
        else:
            suggestion_widget.update("")

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
            self.action_next_diff()
        elif cmd == "yl":
            self.ai.learn_chunk(current_diff["diff"])
            self.action_next_diff()
        elif cmd == "c":
            if len(parts) < 3:
                self.query_one("#ai-suggestion", Static).update(
                    "[bold red]Error:[/bold red] 'c' command requires a line number and a comment."
                )
                return
            line_num = int(parts[1])
            comment = parts[2]
            self.post_comment(current_diff, line_num, comment)
        elif cmd == "cl":
            if len(parts) < 3:
                self.query_one("#ai-suggestion", Static).update(
                    "[bold red]Error:[/bold red] 'cl' command requires a line number and a comment."
                )
                return
            line_num = int(parts[1])
            comment = parts[2]
            self.ai.learn_chunk(current_diff["diff"], comment=comment)
            self.post_comment(current_diff, line_num, comment)
        else:
            self.query_one("#ai-suggestion", Static).update(
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
            
            self.query_one("#ai-suggestion", Static).update(
                "[bold green]Successfully re-authenticated.[/bold green]"
            )
        except Exception as e:
            self.query_one("#ai-suggestion", Static).update(
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
                "new_path": diff["new_path"],
                "new_line": line_num,
            },
        }

        try:
            self.merge_request.discussions.create(comment_data)
            self.query_one("#ai-suggestion", Static).update(
                f"[green]Success:[/green] Comment posted to line {line_num}."
            )
        except gitlab.exceptions.GitlabAuthenticationError:
            self.query_one("#ai-suggestion", Static).update(
                "[bold yellow]Authentication failed. Attempting to re-authenticate...[/bold yellow]"
            )
            self._reauthenticate()
            # Retry posting the comment after re-authentication
            try:
                self.merge_request.discussions.create(comment_data)
                self.query_one("#ai-suggestion", Static).update(
                    f"[green]Success:[/green] Comment posted to line {line_num} after re-authentication."
                )
            except gitlab.exceptions.GitlabError as e:
                self.query_one("#ai-suggestion", Static).update(
                    f"[bold red]Error:[/bold red] Failed to post comment after re-authentication: {e}"
                )
        except gitlab.exceptions.GitlabError as e:
            self.query_one("#ai-suggestion", Static).update(
                f"[bold red]Error:[/bold red] Failed to post comment: {e}"
            )

    def action_next_diff(self):
        """Go to the next diff."""
        if self.current_diff_index < len(self.diffs) - 1:
            self.current_diff_index += 1
            self.show_current_diff()
        else:
            self.query_one("#ai-suggestion", Static).update("All diffs reviewed.")

    def action_prev_diff(self):
        """Go to the previous diff."""
        if self.current_diff_index > 0:
            self.current_diff_index -= 1
            self.show_current_diff()

    def action_clear_input(self):
        """Clear the command input-field."""
        self.query_one("#command-input", Input).value = ""
