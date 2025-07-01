from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget
from textual.containers import Horizontal, Vertical
from textual.events import MouseScrollDown, MouseScrollUp
from textual.message import Message

class SyncedVertical(Vertical):
    """A Vertical container that stops default scrolling and posts a custom sync message."""

    class SyncScroll(Message):
        """A message to synchronize scrolling."""
        def __init__(self, direction: str) -> None:
            super().__init__()
            self.direction = direction

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Stop the default scroll and notify the parent."""
        event.stop()
        self.post_message(self.SyncScroll("down"))

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Stop the default scroll and notify the parent."""
        event.stop()
        self.post_message(self.SyncScroll("up"))


class DiffView(Widget):
    """A widget to display a simple, side-by-side diff with synchronized scrolling."""

    SCROLL_STEP = 2

    def __init__(self, diff: dict, current_diff_index: int, total_diffs: int):
        """
        Initialize the DiffView.

        Args:
            diff (dict): A dictionary representing a single file change from the GitLab API.
            current_diff_index (int): The index of the current diff.
            total_diffs (int): The total number of diffs.
        """
        super().__init__()
        self.diff_data = diff
        self.current_diff_index = current_diff_index
        self.total_diffs = total_diffs

    def compose(self) -> ComposeResult:
        """Compose the static layout of the diff view."""
        file_path = escape(self.diff_data.get('new_path', 'Unknown file'))
        counter_text = f"Diff {self.current_diff_index + 1} of {self.total_diffs}"
        
        with Horizontal(classes="diff-header"):
            yield Static(f"[bold]{file_path}[/bold]", classes="filename")
            yield Static(counter_text, classes="counter")

        with Horizontal(id="diff-container"):
            yield SyncedVertical(classes="diff-panel", id="old-pane")
            yield SyncedVertical(classes="diff-panel", id="new-pane")

    def on_mount(self) -> None:
        """Called when the widget is mounted. Populates the diff view with content."""
        old_pane = self.query_one("#old-pane", SyncedVertical)
        new_pane = self.query_one("#new-pane", SyncedVertical)

        old_pane.mount(Static("[bold]Old[/bold]", classes="diff-header-panes"))
        new_pane.mount(Static("[bold]New[/bold]", classes="diff-header-panes"))

        diff_lines = self.diff_data['diff'].split('\n')
        
        hunk_header = next((line for line in diff_lines if line.startswith('@@')), None)
        old_ln_start, new_ln_start = 0, 0
        if hunk_header:
            parts = hunk_header.split(' ')
            if len(parts) > 2:
                old_ln_start = abs(int(parts[1].split(',')[0]))
                new_ln_start = abs(int(parts[2].split(',')[0]))

        current_old_ln = old_ln_start
        current_new_ln = new_ln_start

        content_lines = [line for line in diff_lines if not line.startswith('@@')]

        for line in content_lines:
            line_content = line[1:]
            
            if line.startswith('-'):
                line_text = f"{current_old_ln:<4} {line_content}"
                static = Static(Text(line_text))
                static.styles.background = "darkred"
                old_pane.mount(static)
                new_pane.mount(Static(" "))
                current_old_ln += 1
            elif line.startswith('+'):
                line_text = f"{current_new_ln:<4} {line_content}"
                static = Static(Text(line_text))
                static.styles.background = "darkgreen"
                new_pane.mount(static)
                old_pane.mount(Static(" "))
                current_new_ln += 1
            elif line.startswith(' '): 
                old_line_text = f"{current_old_ln:<4} {line_content}"
                new_line_text = f"{current_new_ln:<4} {line_content}"
                old_pane.mount(Static(Text(old_line_text)))
                new_pane.mount(Static(Text(new_line_text)))
                current_old_ln += 1
                current_new_ln += 1
            else:
                old_pane.mount(Static(Text(line)))
                new_pane.mount(Static(Text(line)))

    def on_synced_vertical_sync_scroll(self, message: SyncedVertical.SyncScroll) -> None:
        """Handles the custom scroll event to scroll both panes by a fixed step."""
        old_pane = self.query_one("#old-pane", SyncedVertical)
        new_pane = self.query_one("#new-pane", SyncedVertical)
        
        if message.direction == "down":
            new_scroll_y = old_pane.scroll_y + self.SCROLL_STEP
            old_pane.scroll_y = new_scroll_y
            new_pane.scroll_y = new_scroll_y
        elif message.direction == "up":
            new_scroll_y = old_pane.scroll_y - self.SCROLL_STEP
            old_pane.scroll_y = new_scroll_y
            new_pane.scroll_y = new_scroll_y