from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static

from ghostcrt.vault.vault import Vault, VaultError, WrongMasterKey


class ConfirmResetScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-reset"):
            yield Label("Delete vault and create a new one? This cannot be undone.")
            with Horizontal(id="reset-actions"):
                yield Button("Cancel", id="cancel", variant="default")
                yield Button("Reset vault", id="confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class UnlockScreen(Screen[Vault]):
    """Create or unlock the password vault."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    UnlockScreen {
        align: center middle;
    }
    #unlock-box {
        width: 60;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #unlock-error {
        color: $error;
        margin-top: 1;
    }
    #unlock-warn {
        color: $warning;
        margin-top: 1;
    }
    """

    def __init__(self, vault_path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.vault_path = vault_path
        self._create_mode = not Vault.exists(vault_path)

    def compose(self) -> ComposeResult:
        title = "Create master key" if self._create_mode else "Unlock vault"
        with Vertical(id="unlock-box"):
            yield Label(title, id="unlock-title")
            yield Input(placeholder="Master password", password=True, id="password")
            if self._create_mode:
                yield Input(placeholder="Confirm master password", password=True, id="confirm")
            yield Static("", id="unlock-error")
            yield Static("", id="unlock-warn")
            with Horizontal(id="unlock-actions"):
                yield Button("Continue", id="submit", variant="primary")
                if not self._create_mode:
                    yield Button("Reset vault…", id="reset", variant="error")

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    def _set_error(self, msg: str) -> None:
        self.query_one("#unlock-error", Static).update(msg)

    def _set_warn(self, msg: str) -> None:
        self.query_one("#unlock-warn", Static).update(msg)

    def _switch_to_create(self) -> None:
        self._create_mode = True
        self.refresh(recompose=True)

    @on(Button.Pressed, "#submit")
    def submit(self) -> None:
        self._do_submit()

    @on(Input.Submitted)
    def on_submitted(self) -> None:
        self._do_submit()

    def _do_submit(self) -> None:
        password = self.query_one("#password", Input).value
        self._set_error("")
        self._set_warn("")
        if not password:
            self._set_error("Password cannot be empty.")
            return
        if self._create_mode:
            confirm = self.query_one("#confirm", Input).value
            if password != confirm:
                self._set_error("Passwords do not match.")
                return
            if len(password) < 8:
                self._set_warn("Warning: master password is shorter than 8 characters.")
            try:
                vault = Vault.create(self.vault_path, password)
            except VaultError:
                self._set_error("Unable to create vault. Check disk space and permissions.")
                return
            self.dismiss(vault)
            return
        try:
            vault = Vault.unlock(self.vault_path, password)
        except WrongMasterKey:
            self._set_error("Wrong master key or damaged vault.")
            self.query_one("#password", Input).value = ""
            return
        except VaultError:
            self._set_error("Unable to unlock vault. Check the file and available memory.")
            self.query_one("#password", Input).value = ""
            return
        self.dismiss(vault)

    @on(Button.Pressed, "#reset")
    def reset_vault(self) -> None:
        def handle(confirmed: bool | None) -> None:
            if confirmed:
                try:
                    Vault.reset(self.vault_path)
                except VaultError:
                    self._set_error("Unable to reset vault. Check file permissions.")
                    return
                self._switch_to_create()

        self.app.push_screen(ConfirmResetScreen(), handle)
