from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ActionMenuScreen(ModalScreen[str | None]):
    """Simple vertical list of actions; returns the chosen action id or None."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    ActionMenuScreen {
        align: center middle;
    }
    ActionMenuScreen.anchored {
        align: left top;
    }
    #action-menu-box {
        width: 40;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        /* $surface is transparent under an ANSI palette (our default), which
           would leave this floating box with no fill at all. */
        &:ansi { background: $ansi-background; }
    }
    #action-menu-box Button {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(
        self, title: str, actions: list[tuple[str, str]], *, anchor_id: str | None = None, **kwargs
    ) -> None:
        """actions: list of (id, label)."""
        super().__init__(**kwargs)
        self._title = title
        self._actions = actions
        self._anchor_id = anchor_id
        self.set_class(anchor_id is not None, "anchored")

    def on_mount(self) -> None:
        self.call_after_refresh(self._position_menu)

    def on_resize(self) -> None:
        self.call_after_refresh(self._position_menu)

    def _position_menu(self) -> None:
        if self._anchor_id is None or len(self.app.screen_stack) < 2:
            return
        anchors = self.app.screen_stack[-2].query(f"#{self._anchor_id}")
        if not anchors:
            return
        anchor = anchors.first()
        box = self.query_one("#action-menu-box")
        box.styles.offset = (
            min(anchor.region.x, max(0, self.size.width - box.outer_size.width)),
            min(anchor.region.bottom, max(0, self.size.height - box.outer_size.height)),
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="action-menu-box"):
            yield Label(self._title)
            for action_id, label in self._actions:
                yield Button(label, id=f"act-{action_id}")
            yield Button("Cancel", id="act-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "act-cancel" or not bid.startswith("act-"):
            self.dismiss(None)
            return
        self.dismiss(bid.removeprefix("act-"))
