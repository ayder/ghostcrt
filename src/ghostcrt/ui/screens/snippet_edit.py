from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from ghostcrt.vault.snippets import (
    MAX_NAME_LEN,
    Snippet,
    normalize_snippet_name,
    snippet_text_error,
)

EMPTY_NAME = "Name cannot be empty."
INVALID_NAME = "Name is too long or contains control characters."
TEXT_HINT = "\\n or Enter = new line · \\\\ = literal backslash"


@dataclass(frozen=True)
class SnippetEdit:
    """A finished edit. `text` None deletes the slot."""

    slot: int
    name: str
    text: str | None = field(repr=False)


class SnippetEditModal(ModalScreen[SnippetEdit | None]):
    """Edit one snippet slot. Delete takes two presses; None means cancel."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Cancel")]

    DEFAULT_CSS = """
    SnippetEditModal { align: center middle; }
    #snippet-edit-box {
        width: 64;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #snippet-text { height: 8; }
    #snippet-edit-hint { color: $text-muted; }
    #snippet-edit-error { color: $error; height: auto; min-height: 1; }
    """

    def __init__(self, slot: int, current: Snippet | None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.slot = slot
        self.current = current
        self._delete_armed = False

    def compose(self) -> ComposeResult:
        name = self.current.name if self.current else ""
        text = self.current.text if self.current else ""
        with Vertical(id="snippet-edit-box"):
            yield Label(f"Snippet {self.slot}")
            yield Label("Name")
            yield Input(name, placeholder="short name", max_length=MAX_NAME_LEN, id="snippet-name")
            yield Label("Text")
            yield TextArea(text, soft_wrap=True, show_line_numbers=False, id="snippet-text")
            yield Static(TEXT_HINT, id="snippet-edit-hint", markup=False)
            yield Static("", id="snippet-edit-error", markup=False)
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Delete", id="delete", variant="error", disabled=self.current is None)
                yield Button("Cancel", id="cancel")

    def _error(self, message: str) -> None:
        self.query_one("#snippet-edit-error", Static).update(message)

    @on(Input.Changed, "#snippet-name")
    @on(TextArea.Changed, "#snippet-text")
    def disarm_delete(self) -> None:
        """Editing forgets a Delete warning that was about the previous content."""
        if self._delete_armed:
            self._delete_armed = False
            self._error("")

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        raw_name = self.query_one("#snippet-name", Input).value
        text = self.query_one("#snippet-text", TextArea).text
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        name = normalize_snippet_name(raw_name)
        if name is None:
            self._error(EMPTY_NAME if not raw_name.strip() else INVALID_NAME)
            return
        error = snippet_text_error(text)
        if error is not None:
            self._error(error)
            return
        self.dismiss(SnippetEdit(self.slot, name, text))

    @on(Button.Pressed, "#delete")
    def delete(self) -> None:
        if self.current is None:
            return
        if not self._delete_armed:
            self._delete_armed = True
            self._error(f"Press Delete again to remove snippet {self.slot}.")
            return
        self.dismiss(SnippetEdit(self.slot, self.current.name, None))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
