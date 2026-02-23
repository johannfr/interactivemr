from fuzzywuzzy import fuzz
from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import MouseScrollDown, MouseScrollUp
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Rule, Static

from .comment_dialog import CommentDialog
from .diff_item import DiffItem
from .diff_parser import parse_diff_to_hunks, prepare_string_for_comparison
from .highlighter import LineSpans, build_rich_text, highlight_lines

FUZZY_THRESHOLD = 60


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

    SCROLL_STEP = 1

    def __init__(
        self, diff: DiffItem, current_diff_index: int, total_diffs: int, comments: dict
    ):
        """
        Initialize the DiffView.

        Args:
            diff (dict): A dictionary representing a single file change from the GitLab API.
            current_diff_index (int): The index of the current diff.
            total_diffs (int): The total number of diffs.
            comments (dict): A dictionary of comments for the merge request.
        """
        super().__init__()
        self.diff_item = diff
        self.diff_data = self.diff_item.diff_data
        self.current_diff_index = current_diff_index
        self.total_diffs = total_diffs
        self.comments = comments

    def compose(self) -> ComposeResult:
        """Compose the static layout of the diff view."""
        file_path = escape(self.diff_data.get("new_path", "Unknown file"))
        counter_text = f"Diff {self.current_diff_index + 1} of {self.total_diffs}"
        approved_text = ""

        if self.diff_item.approved:
            approved_text = " (Approved)"

        with Horizontal(classes="diff-header"):
            yield Static(f"[bold]{file_path}[/bold]{approved_text}", classes="filename")
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

        hunks = parse_diff_to_hunks(self.diff_data["diff"])
        file_path = self.diff_data.get("new_path")

        # ------------------------------------------------------------------
        # Pass 1 — collect every content line (stripped of its diff prefix)
        # so we can feed them all to the tree-sitter highlighter in one shot.
        #
        # Each entry in render_plan describes one row that will appear in the
        # diff view.  We record enough information to render it in pass 2
        # without re-parsing the hunks.
        #
        # Entry format (tuple):
        #   ("context", old_ln, new_ln, content)
        #   ("added",   None,   new_ln, content)
        #   ("removed", old_ln, None,   content)
        #   ("rule",)                              — hunk separator
        # ------------------------------------------------------------------

        render_plan: list[tuple] = []

        current_old_ln = 0
        current_new_ln = 0

        for i, hunk in enumerate(hunks):
            if i > 0:
                render_plan.append(("rule",))

            parts = hunk.header.split(" ")
            if len(parts) > 2:
                current_old_ln = abs(int(parts[1].split(",")[0]))
                current_new_ln = abs(int(parts[2].split(",")[0]))

            line_idx = 0
            while line_idx < len(hunk.lines):
                line_type, line_content = hunk.lines[line_idx]

                if line_type == " ":
                    render_plan.append(
                        ("context", current_old_ln, current_new_ln, line_content)
                    )
                    current_old_ln += 1
                    current_new_ln += 1
                    line_idx += 1
                    continue

                if line_type == "+":
                    render_plan.append(("added", None, current_new_ln, line_content))
                    current_new_ln += 1
                    line_idx += 1
                    continue

                # Collect a block of consecutive '-' then '+' lines.
                removed_lines: list[str] = []
                added_lines: list[str] = []

                temp_idx = line_idx
                while temp_idx < len(hunk.lines) and hunk.lines[temp_idx][0] == "-":
                    removed_lines.append(hunk.lines[temp_idx][1])
                    temp_idx += 1
                while temp_idx < len(hunk.lines) and hunk.lines[temp_idx][0] == "+":
                    added_lines.append(hunk.lines[temp_idx][1])
                    temp_idx += 1

                removed_ptr, added_ptr = 0, 0
                while removed_ptr < len(removed_lines) and added_ptr < len(added_lines):
                    removed_line = removed_lines[removed_ptr]
                    added_line = added_lines[added_ptr]
                    clean_removed = prepare_string_for_comparison(removed_line)
                    clean_added = prepare_string_for_comparison(added_line)

                    if (
                        fuzz.token_sort_ratio(clean_removed, clean_added)
                        > FUZZY_THRESHOLD
                    ):
                        render_plan.append(
                            (
                                "changed",
                                current_old_ln,
                                current_new_ln,
                                removed_line,
                                added_line,
                            )
                        )
                        current_old_ln += 1
                        current_new_ln += 1
                        removed_ptr += 1
                        added_ptr += 1
                    else:
                        render_plan.append(
                            ("removed", current_old_ln, None, removed_line)
                        )
                        current_old_ln += 1
                        removed_ptr += 1

                while removed_ptr < len(removed_lines):
                    render_plan.append(
                        ("removed", current_old_ln, None, removed_lines[removed_ptr])
                    )
                    current_old_ln += 1
                    removed_ptr += 1

                while added_ptr < len(added_lines):
                    render_plan.append(
                        ("added", None, current_new_ln, added_lines[added_ptr])
                    )
                    current_new_ln += 1
                    added_ptr += 1

                line_idx = temp_idx

        # ------------------------------------------------------------------
        # Collect all unique content lines for the highlighter.
        # "changed" entries contribute two lines (old and new); all others
        # contribute one.  We build a flat list and a per-plan-entry index.
        # ------------------------------------------------------------------

        all_lines: list[str] = []
        plan_to_span_idx: list[
            tuple[int, ...]
        ] = []  # indices into all_lines per plan entry

        for entry in render_plan:
            if entry[0] == "rule":
                plan_to_span_idx.append(())
            elif entry[0] == "changed":
                _, _old_ln, _new_ln, old_content, new_content = entry
                plan_to_span_idx.append((len(all_lines), len(all_lines) + 1))
                all_lines.append(old_content.rstrip("\n"))
                all_lines.append(new_content.rstrip("\n"))
            else:
                content = entry[3]
                plan_to_span_idx.append((len(all_lines),))
                all_lines.append(content.rstrip("\n"))

        # One tree-sitter parse for every content line in this diff.
        spans: list[LineSpans] = highlight_lines(all_lines, file_path or "")

        # ------------------------------------------------------------------
        # Pass 2 — render using the pre-computed spans.
        # ------------------------------------------------------------------

        for entry, span_indices in zip(render_plan, plan_to_span_idx):
            kind = entry[0]

            if kind == "rule":
                old_pane.mount(Rule())
                new_pane.mount(Rule())
                continue

            if kind == "context":
                _, old_ln, new_ln, _content = entry
                idx = span_indices[0]
                comment_indicator = self._get_comment_indicator(file_path, new_ln)
                old_pane.mount(Static(build_rich_text(old_ln, spans[idx])))
                new_pane.mount(
                    Static(
                        build_rich_text(new_ln, spans[idx], indicator=comment_indicator)
                    )
                )
                continue

            if kind == "added":
                _, _old_ln, new_ln, _content = entry
                idx = span_indices[0]
                comment_indicator = self._get_comment_indicator(file_path, new_ln)
                new_static = Static(
                    build_rich_text(new_ln, spans[idx], indicator=comment_indicator)
                )
                new_static.styles.background = "darkgreen"
                new_pane.mount(new_static)
                old_pane.mount(Static(" "))
                continue

            if kind == "removed":
                _, old_ln, _new_ln, _content = entry
                idx = span_indices[0]
                old_static = Static(build_rich_text(old_ln, spans[idx]))
                old_static.styles.background = "darkred"
                old_pane.mount(old_static)
                new_pane.mount(Static(" "))
                continue

            if kind == "changed":
                _, old_ln, new_ln, _old_content, _new_content = entry
                old_idx, new_idx = span_indices
                comment_indicator = self._get_comment_indicator(file_path, new_ln)

                old_static = Static(build_rich_text(old_ln, spans[old_idx]))
                old_static.styles.background = "darkred"
                old_pane.mount(old_static)

                new_static = Static(
                    build_rich_text(new_ln, spans[new_idx], indicator=comment_indicator)
                )
                new_static.styles.background = "darkgreen"
                new_pane.mount(new_static)

    def _get_comment_indicator(self, file_path: str | None, line_number: int) -> str:
        """Returns a comment indicator if a comment exists for the given line."""
        if file_path and (file_path, line_number) in self.comments:
            return f"[@click=app.show_comments('{file_path}',{line_number})][bold white]C[/bold white][/@click] "
        return "  "

    def on_synced_vertical_sync_scroll(
        self, message: SyncedVertical.SyncScroll
    ) -> None:
        """Handles the custom scroll event to scroll both panes by a fixed step."""
        if message.direction == "down":
            self.scroll_panes(self.SCROLL_STEP)
        elif message.direction == "up":
            self.scroll_panes(-self.SCROLL_STEP)

    def scroll_panes(self, delta: int) -> None:
        """Scrolls both panes by a given delta."""
        try:
            old_pane = self.query_one("#old-pane", SyncedVertical)
            new_pane = self.query_one("#new-pane", SyncedVertical)
        except Exception:
            return

        new_scroll_y = old_pane.scroll_y + delta
        if new_scroll_y < 0:
            new_scroll_y = 0

        old_pane.scroll_y = new_scroll_y
        new_pane.scroll_y = new_scroll_y
        self.refresh()

    def scroll_up_step(self) -> None:
        """Scroll up by one step."""
        self.scroll_panes(-self.SCROLL_STEP)

    def scroll_down_step(self) -> None:
        """Scroll down by one step."""
        self.scroll_panes(self.SCROLL_STEP)

    def page_up(self) -> None:
        """Scroll up by one page."""
        try:
            pane = self.query_one("#old-pane", SyncedVertical)
            page_size = pane.size.height
            self.scroll_panes(-page_size)
        except Exception:
            pass

    def page_down(self) -> None:
        """Scroll down by one page."""
        try:
            pane = self.query_one("#old-pane", SyncedVertical)
            page_size = pane.size.height
            self.scroll_panes(page_size)
        except Exception:
            pass

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
                    new_ln_str = parts[2].split(",")[0]
                    current_new_ln = abs(int(new_ln_str))
                continue

            if line.startswith("+") or line.startswith(" "):
                content_line_counter += 1
                if content_line_counter == diff_line_index:
                    return current_new_ln
                current_new_ln += 1
            elif line.startswith("-"):
                pass

        return -1  # Should not be reached for valid inputs
