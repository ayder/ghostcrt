from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class VaultEditModal(ModalScreen[tuple[str, str] | str | None]):
    """Manage vault password for an alias.

    Returns:
      ("set", password) on save
      "delete" on delete
      None on cancel
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    VaultEditModal {
        align: center middle;
    }
    #vault-edit-box {
        width: 60;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    """

    def __init__(self, alias: str, has_password: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.alias = alias
        self.has_password = has_password

    def compose(self) -> ComposeResult:
        with Vertical(id="vault-edit-box"):
            yield Label(f"Vault password for {self.alias}")
            yield Input(placeholder="SSH password", password=True, id="password")
            yield Static("", id="vault-edit-error")
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                if self.has_password:
                    yield Button("Delete", id="delete", variant="error")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        pw = self.query_one("#password", Input).value
        if not pw:
            self.query_one("#vault-edit-error", Static).update("Password cannot be empty.")
            return
        self.dismiss(("set", pw))

    @on(Button.Pressed, "#delete")
    def delete(self) -> None:
        self.dismiss("delete")

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
