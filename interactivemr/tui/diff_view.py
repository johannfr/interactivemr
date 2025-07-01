from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget
from textual.containers import Horizontal, Vertical
from textual.events import MouseScrollDown, MouseScrollUp
from textual.message import Message
from .comment_dialog import CommentDialog

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

    def __init__(self, diff: dict, current_diff_index: int, total_diffs: int, comments: dict):
        """
        Initialize the DiffView.

        Args:
            diff (dict): A dictionary representing a single file change from the GitLab API.
            current_diff_index (int): The index of the current diff.
            total_diffs (int): The total number of diffs.
            comments (dict): A dictionary of comments for the merge request.
        """
        super().__init__()
        self.diff_data = diff
        self.current_diff_index = current_diff_index
        self.total_diffs = total_diffs
        self.comments = comments

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
        
        current_old_ln = 0
        current_new_ln = 0
        file_path = self.diff_data.get('new_path')

        for line in diff_lines:
            if line.startswith('@@'):
                parts = line.split(' ')
                if len(parts) > 2:
                    current_old_ln = abs(int(parts[1].split(',')[0]))
                    current_new_ln = abs(int(parts[2].split(',')[0]))
                continue

            line_content = escape(line[1:]) if len(line) > 0 else ""
            
            if (file_path, current_new_ln) in self.comments:
                comment_indicator = f"[@click=app.show_comments('{file_path}',{current_new_ln})][bold white]C[/bold white][/@click] "
            else:
                comment_indicator = "  "

            if line.startswith('-'):
                line_text = f"{current_old_ln:<4} {line_content}"
                static = Static(Text.from_markup(line_text))
                static.styles.background = "darkred"
                old_pane.mount(static)
                new_pane.mount(Static(" "))
                current_old_ln += 1
            elif line.startswith('+'):
                line_text = f"{current_new_ln:<4}{comment_indicator}{line_content}"
                static = Static(Text.from_markup(line_text))
                static.styles.background = "darkgreen"
                new_pane.mount(static)
                old_pane.mount(Static(" "))
                current_new_ln += 1
            elif line.startswith(' '): 
                old_line_text = f"{current_old_ln:<4} {line_content}"
                new_line_text = f"{current_new_ln:<4}{comment_indicator}{line_content}"
                old_pane.mount(Static(Text.from_markup(old_line_text)))
                new_pane.mount(Static(Text.from_markup(new_line_text)))
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

        self.refresh()
        
    def get_line_number_for_comment(self, diff_line_index: int) -> int:
        """
        Translate a 1-based index from the visible diff content to the
        actual line number in the new file.
        """
        diff_lines = self.diff_data["diff"].split("\n")

        current_new_ln = 0
        content_line_counter = 0

        for line in diff_lines:
            if line.startswith("@@"):
                parts = line.split(" ")
                if len(parts) > 2:
                    # Correctly parse the starting line number for the new file
                    new_ln_str = parts[2].split(",")[0]
                    current_new_ln = abs(int(new_ln_str))
                continue

            # Only count lines that appear in the new file view
            if line.startswith("+") or line.startswith(" "):
                content_line_counter += 1
                if content_line_counter == diff_line_index:
                    return current_new_ln
                current_new_ln += 1
            elif line.startswith("-"):
                # This line does not exist in the new file, so we don't increment
                # the content line counter or the new line number.
                pass

        return -1  # Should not be reached for valid inputs
