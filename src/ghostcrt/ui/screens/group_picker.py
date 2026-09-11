from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

NO_CHOICE = "Choose a group or type a new name."
LABEL_CHOOSE = "Choose"
LABEL_CREATE = "Create"


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
    #group-picker-error {
        color: $error;
        height: auto;
        min-height: 1;
    }
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
                # The box starts empty, so on open the button can only choose.
                yield Button(LABEL_CHOOSE, id="create", variant="primary")
                yield Button("Cancel", id="cancel")
            yield Static("", id="group-picker-error")

    def _error(self, msg: str) -> None:
        self.query_one("#group-picker-error", Static).update(msg)

    def _highlighted_group(self) -> str | None:
        """The highlighted entry's group name, or None when nothing is highlighted.

        Nothing is highlighted when the dialog opens, so this is the state the
        operator is in before they move the cursor.
        """
        options = self.query_one("#group-options", OptionList)
        index = options.highlighted
        if index is None:
            return None
        return str(options.get_option_at_index(index).id)

    @on(OptionList.OptionSelected, "#group-options")
    def choose(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    @on(Input.Changed, "#new-group")
    def follow_state(self, event: Input.Changed) -> None:
        """Typing a name turns Choose into Create; clearing the box turns it back."""
        self.query_one("#create", Button).label = (
            LABEL_CREATE if event.value.strip() else LABEL_CHOOSE
        )

    @on(Button.Pressed, "#create")
    def create(self) -> None:
        """Answer with the typed name, else the highlighted group, else stay open.

        The typed name wins over the highlight, and the caller creates it if it
        is new. The empty string is never an answer: with nothing typed and
        nothing highlighted there is no group to return, so the dialog says so
        and waits rather than dismissing as if it had been cancelled.
        """
        name = self.query_one("#new-group", Input).value.strip()
        if name:
            self.dismiss(name)
            return
        group = self._highlighted_group()
        if group is None:
            self._error(NO_CHOICE)
            return
        self.dismiss(group)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
