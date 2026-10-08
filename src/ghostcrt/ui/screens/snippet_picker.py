from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option

from ghostcrt.ui.widgets.choice_list import ChoiceList
from ghostcrt.vault.snippets import SLOTS, Snippet

SLOT_OPTION_PREFIX = "slot:"


class SnippetPickerScreen(ModalScreen[int | None]):
    """Pick a snippet slot to edit. None means cancel."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Cancel")]

    DEFAULT_CSS = """
    SnippetPickerScreen { align: center middle; }
    #snippet-picker-box {
        width: 44;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #snippet-options { height: auto; max-height: 7; }
    """

    def __init__(self, snippets: list[Snippet], **kwargs) -> None:
        super().__init__(**kwargs)
        self._names = {snippet.slot: snippet.name for snippet in snippets}

    def compose(self) -> ComposeResult:
        with Vertical(id="snippet-picker-box"):
            yield Label("Snippets")
            options = ChoiceList(id="snippet-options")
            for slot in SLOTS:
                name = self._names.get(slot, "(empty)")
                options.add_option(Option(f"{slot}  {name}", id=f"{SLOT_OPTION_PREFIX}{slot}"))
            yield options
            with Horizontal():
                yield Button("Cancel", id="cancel")

    @on(OptionList.OptionSelected, "#snippet-options")
    def choose(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(str(event.option.id).removeprefix(SLOT_OPTION_PREFIX)))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
