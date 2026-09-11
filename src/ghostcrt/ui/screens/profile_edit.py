from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ghostcrt.vault.vault import normalize_profile_id

EMPTY_ID = "Profile id cannot be empty."
INVALID_ID = "Profile id is too long or contains control characters."
EMPTY_PASSWORD = "Password cannot be empty."
OVERWRITE_WARNING = "Existing profile: password will be replaced."


class ProfileEditModal(ModalScreen[tuple[str, str] | None]):
    """Create a profile, or replace the password of one that exists.

    Returns (stripped id, password) on save, None on cancel. Replacing an
    existing password takes two presses: the first arms the id and warns.
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    ProfileEditModal {
        align: center middle;
    }
    #profile-edit-box {
        width: 60;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        /* $surface is transparent under an ANSI palette (our default), which
           would leave this floating box with no fill at all. */
        &:ansi { background: $ansi-background; }
    }
    #profile-edit-error {
        color: $error;
        height: auto;
        min-height: 1;
    }
    """

    def __init__(self, profiles: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.profiles = list(profiles)
        # The id the operator has already been warned about, if any.
        self._armed_id: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="profile-edit-box"):
            yield Label("Create / update profile")
            yield Label("Profile id")
            yield Input(placeholder="profile id", id="profile-id")
            yield Label("Password")
            yield Input(placeholder="SSH password", password=True, id="password")
            yield Static("", id="profile-edit-error")
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    def _error(self, msg: str) -> None:
        self.query_one("#profile-edit-error", Static).update(msg)

    @on(Input.Changed, "#profile-id")
    def forget_warning(self) -> None:
        """Editing the id forgets a warning that was about the previous one."""
        self._armed_id = None

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        raw = self.query_one("#profile-id", Input).value
        password = self.query_one("#password", Input).value
        profile_id = normalize_profile_id(raw)
        if profile_id is None:
            self._error(EMPTY_ID if not raw.strip() else INVALID_ID)
            return
        if not password:
            self._error(EMPTY_PASSWORD)
            return
        if profile_id in self.profiles and profile_id != self._armed_id:
            self._armed_id = profile_id
            self._error(OVERWRITE_WARNING)
            return
        self._error("")
        self.dismiss((profile_id, password))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
