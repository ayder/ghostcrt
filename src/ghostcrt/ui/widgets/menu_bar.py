from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button


class MenuBar(Horizontal):
    DEFAULT_CSS = """
    MenuBar {
        height: 3;
        padding: 0 1;
        background: $surface;
    }
    MenuBar Button {
        margin-right: 1;
        min-width: 12;
    }
    """

    class HostsAction(Message):
        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    class VaultAction(Message):
        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    class SessionAction(Message):
        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def compose(self) -> ComposeResult:
        yield Button("Hosts", id="menu-hosts", flat=True)
        yield Button("Vault", id="menu-vault", flat=True)
        yield Button("Session", id="menu-session", flat=True)
        yield Button("Help", id="menu-help", flat=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "menu-help":
            from ghostcrt.ui.screens.help import HelpScreen

            self.app.push_screen(HelpScreen())
        elif bid == "menu-hosts":
            self.post_message(self.HostsAction("menu"))
        elif bid == "menu-vault":
            self.post_message(self.VaultAction("menu"))
        elif bid == "menu-session":
            self.post_message(self.SessionAction("menu"))
