from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets.option_list import Option


class GroupPickerScreen(ModalScreen[str | None]):
    """Pick an existing group, or type a new one. Returns the name, or None."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Cancel")]

    DEFAULT_CSS = """
    GroupPickerScreen { align: center middle; }
    #group-picker-box {
        width: 50;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #group-options { height: auto; max-height: 10; }
    """

    def __init__(self, groups: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.groups = groups

    def compose(self) -> ComposeResult:
        with Vertical(id="group-picker-box"):
            yield Label("Choose a group")
            options = OptionList(id="group-options")
            for name in self.groups:
                options.add_option(Option(name, id=name))
            yield options
            yield Label("or create a new one")
            yield Input(placeholder="new-group", id="new-group")
            with Horizontal():
                yield Button("Create", id="create", variant="primary")
                yield Button("Cancel", id="cancel")

    @on(OptionList.OptionSelected, "#group-options")
    def choose(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    @on(Button.Pressed, "#create")
    def create(self) -> None:
        name = self.query_one("#new-group", Input).value.strip()
        self.dismiss(name or None)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
