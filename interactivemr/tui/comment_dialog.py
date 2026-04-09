import gitlab
from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Rule, Static


class CommentDialog(Screen):
    """A dialog to display and resolve comment threads on a merge request."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, comments: list[dict], title: str, merge_request) -> None:
        """Initialise the dialog.

        Args:
            comments: List of comment entry dicts, each containing at minimum
                ``body``, ``author``, ``discussion_id``, ``resolvable``, and
                ``resolved`` keys.
            title: Header text shown at the top of the dialog.
            merge_request: The python-gitlab ``ProjectMergeRequest`` object,
                used to resolve threads via the API.
        """
        super().__init__()
        self.comments = comments
        self.dialog_title = title
        self.merge_request = merge_request
        # Map button id → comment entry for the resolve handler.
        self._button_to_comment: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        """Build the per-thread layout."""
        # Group notes by discussion_id so each thread gets one resolve button.
        threads: dict[str, list[dict]] = {}
        thread_order: list[str] = []
        for comment in self.comments:
            disc_id = comment.get("discussion_id", "")
            if disc_id not in threads:
                threads[disc_id] = []
                thread_order.append(disc_id)
            threads[disc_id].append(comment)

        with Vertical(id="comment-dialog"):
            yield Static(self.dialog_title, id="comment-dialog-title")
            with Vertical(id="comment-dialog-scroll"):
                first = True
                for disc_id in thread_order:
                    if not first:
                        yield Rule()
                    first = False
                    thread_comments = threads[disc_id]
                    # All notes in a thread share the same resolution state.
                    resolvable = thread_comments[0].get("resolvable", False)
                    resolved = thread_comments[0].get("resolved", False)

                    for c in thread_comments:
                        yield Static(
                            f"[bold]{escape(c['author'])}:[/bold] {escape(c['body'])}",
                            classes="comment-body",
                        )

                    if resolvable:
                        btn_id = f"resolve-{disc_id}"
                        self._button_to_comment[btn_id] = thread_comments[0]
                        if resolved:
                            yield Button(
                                "Resolved",
                                id=btn_id,
                                variant="success",
                                disabled=True,
                                classes="resolve-btn",
                            )
                        else:
                            yield Button(
                                "Resolve thread",
                                id=btn_id,
                                variant="warning",
                                classes="resolve-btn",
                            )

            yield Button("Close", variant="primary", id="comment-dialog-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Close and per-thread Resolve buttons."""
        btn_id = event.button.id
        if btn_id == "comment-dialog-close":
            self.app.pop_screen()
        elif btn_id and btn_id.startswith("resolve-"):
            discussion_id = btn_id.removeprefix("resolve-")
            self._resolve_thread(discussion_id, event.button)

    def action_close(self) -> None:
        """Close the dialog (bound to Escape)."""
        self.app.pop_screen()

    def _resolve_thread(self, discussion_id: str, button: Button) -> None:
        """Resolve a discussion thread via the GitLab API.

        Args:
            discussion_id: The GitLab discussion ID to resolve.
            button: The button that was pressed, updated on success.
        """
        try:
            discussion = self.merge_request.discussions.get(discussion_id)
            discussion.resolved = True
            discussion.save()
        except gitlab.exceptions.GitlabAuthenticationError:
            self.app.query_one("#status-field", Static).update(
                "[bold yellow]Authentication failed. Attempting to re-authenticate...[/bold yellow]"
            )
            self.app._reauthenticate()
            try:
                discussion = self.merge_request.discussions.get(discussion_id)
                discussion.resolved = True
                discussion.save()
            except gitlab.exceptions.GitlabError as e:
                self.app.query_one("#status-field", Static).update(
                    f"[bold red]Error:[/bold red] Failed to resolve thread after re-authentication: {e.response_code}"
                )
                return
        except gitlab.exceptions.GitlabError as e:
            self.app.query_one("#status-field", Static).update(
                f"[bold red]Error:[/bold red] Failed to resolve thread: {e.response_code}"
            )
            return

        # Success — update button state and propagate to the app's data model.
        button.label = "Resolved"
        button.variant = "success"
        button.disabled = True
        if discussion_id in self.app.discussion_resolved:
            self.app.discussion_resolved[discussion_id] = True
        # Update resolved flag on every comment entry for this thread so the
        # C indicator color is correct when the diff view is next rendered.
        for c in self.comments:
            if c.get("discussion_id") == discussion_id:
                c["resolved"] = True
        # Reload comments and refresh the diff view so C colors update.
        self.app._load_comments()
        self.app.show_current_diff()
        self.app.query_one("#status-field", Static).update(
            "[bold green]Thread resolved.[/bold green]"
        )

    CSS = """
    #comment-dialog {
        width: 100%;
        height: 100%;
        border: thick $primary 80%;
        background: $surface;
        padding: 0 1;
    }

    #comment-dialog-title {
        width: 100%;
        content-align: center middle;
        text-align: center;
        padding: 1 0;
        text-style: bold;
    }

    #comment-dialog-scroll {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }

    .comment-body {
        margin: 0 0 0 1;
    }

    .resolve-btn {
        margin: 1 0 0 0;
        width: 100%;
    }

    #comment-dialog-close {
        width: 100%;
        margin: 1 0 0 0;
        height: 3;
    }
    """
