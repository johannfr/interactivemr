from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import Screen
from textual.widgets import Button, Static


class CommentDialog(Screen):
    """A dialog to display comments."""

    def __init__(self, comments: list[str], line_number: int) -> None:
        super().__init__()
        self.comments = comments
        self.line_number = line_number

    def compose(self) -> ComposeResult:
        yield Grid(
            Static(f"Comments for line {self.line_number}", id="comment-dialog-title"),
            Static("\n---\n".join(self.comments), id="comment-dialog-content"),
            Button("Close", variant="primary", id="comment-dialog-close"),
            id="comment-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        self.app.pop_screen()

    CSS = """
    #comment-dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 0 1;
        width: 80%;
        height: 80%;
        border: thick $primary 80%;
        background: $surface;
    }

    #comment-dialog-title {
        column-span: 2;
        width: 100%;
        content-align: center middle;
    }

    #comment-dialog-content {
        column-span: 2;
        overflow: auto;
    }

    #comment-dialog-close {
        column-span: 2;
        width: 100%;
    }
    """

