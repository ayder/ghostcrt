from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.content import Content
from textual.message import Message
from textual.widgets import Button

from ghostcrt.vault.snippets import SLOTS, Snippet


class SnippetButton(Button, can_focus=False):
    """Types its slot on click without taking focus from the terminal."""

    def __init__(self, slot: int) -> None:
        super().__init__(str(slot), id=f"snippet-{slot}", flat=True)
        self.slot = slot


class SnippetBar(Horizontal):
    """Footer buttons for the defined snippets; shown while a terminal is focused."""

    DEFAULT_CSS = """
    SnippetBar {
        width: auto;
        height: 1;
        display: none;
    }
    SnippetBar.-active {
        display: block;
    }
    SnippetBar SnippetButton {
        min-width: 0;
        height: 1;
        margin: 0 0 0 1;
    }
    """

    class Chosen(Message):
        def __init__(self, slot: int) -> None:
            super().__init__()
            self.slot = slot

    def compose(self) -> ComposeResult:
        for slot in SLOTS:
            yield SnippetButton(slot)

    def show_snippets(self, snippets: list[Snippet]) -> None:
        names = {snippet.slot: snippet.name for snippet in snippets}
        # A button is its label, a column of padding each side and a one-column
        # gap. Past half the screen, show slot numbers only, so the hint (which
        # tells whether Ctrl+N is armed) and every button stay on screen.
        full_width = sum(len(f"{slot} {name}") + 3 for slot, name in names.items())
        numbers_only = full_width > self.app.size.width // 2
        for button in self.query(SnippetButton):
            name = names.get(button.slot)
            button.display = name is not None
            if name is not None:
                label = str(button.slot) if numbers_only else f"{button.slot} {name}"
                # Content, not str: a str label is parsed as markup.
                button.label = Content(label)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if isinstance(event.button, SnippetButton):
            self.post_message(self.Chosen(event.button.slot))
