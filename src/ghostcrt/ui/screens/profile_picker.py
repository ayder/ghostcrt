from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option

NONE_OPTION_ID = "none"
PROFILE_OPTION_PREFIX = "profile:"


@dataclass(frozen=True)
class ProfilePick:
    """A choice made in the picker. `profile` is None for the `(none)` entry.

    Cancelling dismisses None instead, so callers test `result is None` and
    never truthiness: ProfilePick(None) is a real choice.
    """

    profile: str | None


class ProfilePickerScreen(ModalScreen[ProfilePick | None]):
    """Pick a profile id, optionally offering `(none)`. None means cancel."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Cancel")]

    DEFAULT_CSS = """
    ProfilePickerScreen { align: center middle; }
    #profile-picker-box {
        width: 50;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #profile-options { height: auto; max-height: 10; }
    """

    def __init__(
        self,
        title: str,
        profiles: list[str],
        *,
        allow_none: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self.profiles = list(profiles)
        self.allow_none = allow_none

    def compose(self) -> ComposeResult:
        with Vertical(id="profile-picker-box"):
            yield Label(self._title)
            options = OptionList(id="profile-options")
            if self.allow_none:
                options.add_option(Option("(none)", id=NONE_OPTION_ID))
            for name in self.profiles:
                options.add_option(Option(name, id=f"{PROFILE_OPTION_PREFIX}{name}"))
            yield options
            with Horizontal():
                yield Button("Cancel", id="cancel")

    @on(OptionList.OptionSelected, "#profile-options")
    def choose(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id)
        if option_id == NONE_OPTION_ID:
            self.dismiss(ProfilePick(None))
            return
        self.dismiss(ProfilePick(option_id.removeprefix(PROFILE_OPTION_PREFIX)))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)
