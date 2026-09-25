from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class HelpScreen(ModalScreen[None]):
    """Compact keyboard reference available from anywhere in the app."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-box {
        width: 68;
        max-width: 94%;
        height: auto;
        max-height: 90%;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #help-intro, #help-close-hint {
        color: $text-muted;
        height: auto;
        margin-bottom: 1;
    }
    #help-shortcuts {
        grid-size: 2;
        grid-columns: 13 1fr;
        grid-rows: auto;
        grid-gutter: 0 1;
        height: auto;
    }
    .help-key {
        color: $accent;
    }
    #help-close {
        margin-top: 1;
    }
    """

    SHORTCUTS: ClassVar[list[tuple[str, str]]] = [
        ("ctrl+n", "Focus the Hosts list."),
        ("/", "Search and filter hosts (outside the terminal)."),
        ("f10", "Focus the menu bar (outside the terminal)."),
        ("escape", "Return from Hosts to the active terminal."),
        ("↑↓ / ←→", "Choose an action / switch open menus."),
        ("enter", "Connect to the selected host."),
        ("ctrl+w", "Close the active SSH session."),
        ("ctrl+t", "Release terminal focus and return to Hosts."),
        ("ctrl+o", "Toggle mouse capture for native terminal selection."),
        ("ctrl+p", "Open the command palette and theme picker."),
        ("ctrl+h", "Show or close this help window."),
        ("ctrl+q", "Close sessions and quit ghostcrt."),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Label("Keyboard help")
            yield Static(
                "Ctrl shortcuts work in the terminal. Release focus with Ctrl+T for UI navigation.",
                id="help-intro",
            )
            with Grid(id="help-shortcuts"):
                for key, explanation in self.SHORTCUTS:
                    yield Static(key, classes="help-key")
                    yield Static(explanation)
            yield Static("Press ctrl+h again or escape to close.", id="help-close-hint")
            yield Button("Close", id="help-close", variant="primary")

    @on(Button.Pressed, "#help-close")
    def close(self) -> None:
        self.dismiss()
