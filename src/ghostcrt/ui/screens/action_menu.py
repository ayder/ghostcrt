from __future__ import annotations

from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ghostcrt.ui.widgets.choice_list import ChoiceList


class ActionMenuScreen(ModalScreen[str | None]):
    """Simple vertical list of actions; returns the chosen action id or None."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Cancel"),
        ("left", "previous_menu", "Previous menu"),
        ("right", "next_menu", "Next menu"),
    ]

    DEFAULT_CSS = """
    ActionMenuScreen {
        align: center middle;
    }
    ActionMenuScreen.anchored {
        align: left top;
    }
    #action-menu-box {
        width: 40;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        /* $surface is transparent under an ANSI palette (our default), which
           would leave this floating box with no fill at all. */
        &:ansi { background: $ansi-background; }
    }
    #action-menu-box Button {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(
        self, title: str, actions: list[tuple[str, str]], *, anchor_id: str | None = None, disabled: set[str] | None = None, **kwargs
    ) -> None:
        """actions: list of (id, label)."""
        super().__init__(**kwargs)
        self._title = title
        self._actions = actions
        self._anchor_id = anchor_id
        self._disabled = disabled or set()
        self.set_class(anchor_id is not None, "anchored")

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.highlighted = next(
            (i for i, option in enumerate(options.options) if not option.disabled), None
        )
        options.focus()
        self.call_after_refresh(self._position_menu)

    def on_resize(self) -> None:
        self.call_after_refresh(self._position_menu)

    def _position_menu(self) -> None:
        if self._anchor_id is None or len(self.app.screen_stack) < 2:
            return
        anchors = self.app.screen_stack[-2].query(f"#{self._anchor_id}")
        if not anchors:
            return
        anchor = anchors.first()
        box = self.query_one("#action-menu-box")
        box.styles.offset = (
            min(anchor.region.x, max(0, self.size.width - box.outer_size.width)),
            min(anchor.region.bottom, max(0, self.size.height - box.outer_size.height)),
        )

    def compose(self) -> ComposeResult:
        yield Static(
            "ghostcrt · Ctrl+H Help · MENU  ↑↓ Choose · ←→ Switch menu · Enter Run · Esc Close",
            id="menu-status",
        )
        with Vertical(id="action-menu-box"):
            options = ChoiceList(id="action-options", compact=True)
            for action_id, label in self._actions:
                if action_id.startswith("delete"):
                    options.add_option(None)
                options.add_option(Option(label, id=action_id, disabled=action_id in self._disabled))
            yield options

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option.disabled:
            self.dismiss(str(event.option.id))

    def on_click(self, event: events.Click) -> None:
        if not self.query_one("#action-menu-box").region.contains(event.screen_x, event.screen_y):
            self.dismiss(None)

    def _switch_menu(self, step: int) -> None:
        anchors = ["menu-hosts", "menu-vault", "menu-session"]
        if self._anchor_id not in anchors:
            return
        parent = self.app.screen_stack[-2]
        target = anchors[(anchors.index(self._anchor_id) + step) % len(anchors)]
        self.dismiss(None)
        def open_menu() -> None:
            button = parent.query_one(f"#{target}")
            # Programmatic presses do not move focus like mouse clicks do.
            # Keep the underlying menu bar focused on the dropdown being opened.
            button.focus()
            button.press()

        parent.call_after_refresh(open_menu)

    def action_previous_menu(self) -> None:
        self._switch_menu(-1)

    def action_next_menu(self) -> None:
        self._switch_menu(1)
