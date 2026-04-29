from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import gitlab
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

PAGE_SIZE = 50


@dataclass
class MRSelection:
    """Carries the selected MR back to the caller."""
    project_path: str
    mr_iid: int


def _mr_label(mr) -> str:
    """Format a single MR as a display string."""
    iid = mr.iid
    title = mr.title or ""
    author = mr.author.get("username", "?") if isinstance(mr.author, dict) else "?"
    # Truncate long titles so the line stays readable
    if len(title) > 70:
        title = title[:67] + "..."
    # Parse ISO 8601 created_at (e.g. "2024-03-15T10:22:05.123Z")
    created_at = getattr(mr, "created_at", None) or ""
    if created_at:
        # Keep only "YYYY-MM-DD HH:MM"
        created_at = created_at.replace("T", " ")[:16]
    return f"!{iid:<6}  {created_at}  {title:<72}  ({author})"


class MRListScreen(Screen):
    """
    A screen that lists open merge requests grouped into three categories:

    1. Review Requested  — current user is in the reviewers list
    2. All Open MRs      — the rest (not assigned to me, not authored by me)
    3. My MRs            — current user is the author
    """

    BINDINGS = [
        Binding("enter", "select", "Select", show=True, priority=True),
    ]

    CSS = """
    MRListScreen {
        align: center middle;
    }
    #mr-list-container {
        width: 100%;
        height: 100%;
    }
    .section-header {
        background: $primary;
        color: $text;
        padding: 0 2;
        height: 1;
        text-style: bold;
    }
    .empty-hint {
        color: $text-muted;
        padding: 0 4;
        height: 1;
    }
    ListView {
        border: none;
        height: auto;
    }
    ListItem {
        padding: 0 4;
    }
    ListItem.load-more {
        color: $accent;
    }
    #status {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, gl: gitlab.Gitlab, scope, scope_type: str, current_user):
        """
        Parameters
        ----------
        gl          : authenticated Gitlab instance
        scope       : a python-gitlab project *or* group object
        scope_type  : "project" or "group"
        current_user: result of gl.auth() / gl.users.get_current()
        """
        super().__init__()
        self.gl = gl
        self.scope = scope
        self.scope_type = scope_type
        self.current_user = current_user

        # All open MRs fetched from the API
        self._all_mrs: list = []
        # Three categorised sub-lists
        self._review_requested: list = []
        self._others: list = []
        self._my_mrs: list = []

        # Pagination state per section (offset into the respective list)
        self._page: dict[str, int] = {
            "review": 0,
            "others": 0,
            "mine": 0,
        }

        # Map ListItem id → MR object for fast lookup on selection
        self._item_map: dict[str, object] = {}

        # Selected result (set before dismissing)
        self.selection: Optional[MRSelection] = None

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        scope_name = getattr(self.scope, "path_with_namespace", None) or getattr(
            self.scope, "full_path", None
        ) or str(self.scope)
        yield Static(f"Fetching open merge requests for {scope_name}…", id="status")
        yield Static(id="mr-list-container")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._fetch_and_render()

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_and_render(self) -> None:
        status = self.query_one("#status", Static)
        try:
            if self.scope_type == "project":
                mrs = self.scope.mergerequests.list(
                    state="opened", get_all=True, order_by="updated_at", sort="desc"
                )
            else:
                mrs = self.scope.mergerequests.list(
                    state="opened", get_all=True, order_by="updated_at", sort="desc"
                )
        except gitlab.exceptions.GitlabError as e:
            status.update(f"[bold red]Error fetching MRs:[/bold red] {e}")
            return

        uid = self.current_user.id

        for mr in mrs:
            reviewers = mr.reviewers if hasattr(mr, "reviewers") else []
            reviewer_ids = [
                r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
                for r in reviewers
            ]
            author_id = (
                mr.author.get("id") if isinstance(mr.author, dict)
                else getattr(mr.author, "id", None)
            )

            if author_id == uid:
                self._my_mrs.append(mr)
            elif uid in reviewer_ids:
                self._review_requested.append(mr)
            else:
                self._others.append(mr)

        self._all_mrs = mrs
        status.update("")
        self._render_lists()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_lists(self) -> None:
        container = self.query_one("#mr-list-container", Static)
        container.remove_children()

        self._item_map.clear()
        self._page = {"review": 0, "others": 0, "mine": 0}

        self._mount_section(
            container,
            title="── Review Requested ──",
            mrs=self._review_requested,
            section_key="review",
        )
        self._mount_section(
            container,
            title="── All Open MRs ──",
            mrs=self._others,
            section_key="others",
        )
        self._mount_section(
            container,
            title="── My MRs ──",
            mrs=self._my_mrs,
            section_key="mine",
        )

    def _mount_section(self, container, title: str, mrs: list, section_key: str) -> None:
        container.mount(Label(title, classes="section-header"))

        if not mrs:
            container.mount(Label("  (none)", classes="empty-hint"))
            return

        visible = mrs[:PAGE_SIZE]
        items = []
        for mr in visible:
            item_id = f"mr-{section_key}-{mr.iid}"
            li = ListItem(Label(_mr_label(mr)), id=item_id)
            self._item_map[item_id] = mr
            items.append(li)

        if len(mrs) > PAGE_SIZE:
            load_id = f"load-more-{section_key}-0"
            items.append(ListItem(Label(f"  [Load {min(PAGE_SIZE, len(mrs) - PAGE_SIZE)} more…]"), id=load_id, classes="load-more"))

        lv = ListView(*items, id=f"lv-{section_key}")
        container.mount(lv)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        item_id = item.id or ""

        # Handle "load more"
        if item_id.startswith("load-more-"):
            parts = item_id.split("-")
            # format: load-more-<section_key>-<page>
            section_key = parts[2]
            current_page = int(parts[3])
            self._load_more(section_key, current_page, item)
            return

        mr = self._item_map.get(item_id)
        if mr is None:
            return

        # Resolve the project path for this MR
        project_path = self._resolve_project_path(mr)
        self.selection = MRSelection(project_path=project_path, mr_iid=int(mr.iid))
        self.app.exit(self.selection)

    def _load_more(self, section_key: str, current_page: int, load_item: ListItem) -> None:
        """Replace the 'load more' item with the next page of MRs."""
        mrs_map = {
            "review": self._review_requested,
            "others": self._others,
            "mine": self._my_mrs,
        }
        mrs = mrs_map[section_key]
        new_page = current_page + 1
        start = new_page * PAGE_SIZE
        end = start + PAGE_SIZE
        next_batch = mrs[start:end]

        lv = self.query_one(f"#lv-{section_key}", ListView)

        # Remove the load-more item
        load_item.remove()

        # Append new items
        new_items = []
        for mr in next_batch:
            item_id = f"mr-{section_key}-{mr.iid}"
            li = ListItem(Label(_mr_label(mr)), id=item_id)
            self._item_map[item_id] = mr
            new_items.append(li)

        if end < len(mrs):
            remaining = len(mrs) - end
            load_id = f"load-more-{section_key}-{new_page}"
            new_items.append(
                ListItem(Label(f"  [Load {min(PAGE_SIZE, remaining)} more…]"), id=load_id, classes="load-more")
            )

        for li in new_items:
            lv.append(li)

    def _resolve_project_path(self, mr) -> str:
        """Return the project's namespace/path string for a given MR object."""
        # python-gitlab MR objects from a group scope have a `project_id` attribute.
        # From a project scope we already know the path.
        if self.scope_type == "project":
            return self.scope.path_with_namespace
        # Group scope: need to look up the project by id
        try:
            project = self.gl.projects.get(mr.project_id)
            return project.path_with_namespace
        except gitlab.exceptions.GitlabError:
            # Fallback: use references field if available
            refs = getattr(mr, "references", {})
            full_ref = refs.get("full", "") if isinstance(refs, dict) else ""
            # full_ref looks like "group/sub/project!42"
            if "!" in full_ref:
                return full_ref.rsplit("!", 1)[0]
            return str(mr.project_id)

    def action_select(self) -> None:
        """Forward Enter to whichever ListView is currently focused."""
        focused = self.focused
        if isinstance(focused, ListView):
            item = focused.highlighted_child
            if item is not None:
                index = focused.index or 0
                self.post_message(ListView.Selected(focused, item, index))
