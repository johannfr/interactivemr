from __future__ import annotations

from typing import Optional

import gitlab
from textual.app import App, ComposeResult
from textual.binding import Binding

from .mr_list_screen import MRListScreen, MRSelection


class MRPickerApp(App):
    """
    A minimal bootstrapping App whose sole purpose is to present the
    MRListScreen and collect the user's MR selection.

    After ``app.run()`` returns, read ``app.selection`` to get the chosen
    ``MRSelection`` (or ``None`` if the user quit without selecting).
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("enter", "select_mr", "Select", show=True, priority=False),
        Binding("up", "scroll_up", "Up", show=False),
        Binding("down", "scroll_down", "Down", show=False),
    ]

    def __init__(self, gl: gitlab.Gitlab, scope, scope_type: str, current_user):
        super().__init__()
        self.gl = gl
        self.scope = scope
        self.scope_type = scope_type
        self.current_user = current_user
        self.selection: Optional[MRSelection] = None

    def on_mount(self) -> None:
        self.theme = "gruvbox"
        self.push_screen(
            MRListScreen(
                gl=self.gl,
                scope=self.scope,
                scope_type=self.scope_type,
                current_user=self.current_user,
            )
        )

    def action_select_mr(self) -> None:
        """Placeholder so Enter shows in the footer; ListView handles the actual selection."""

    def compose(self) -> ComposeResult:
        # The real content is pushed as a Screen; nothing to compose here.
        return iter([])
