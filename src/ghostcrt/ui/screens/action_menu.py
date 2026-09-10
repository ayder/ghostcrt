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

    def __init__(self, title: str, actions: list[tuple[str, str]], **kwargs) -> None:
        """actions: list of (id, label)."""
        super().__init__(**kwargs)
        self._title = title
        self._actions = actions

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
