from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmCloseScreen(ModalScreen[bool]):
    """Confirm termination, with cancellation selected by default."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ConfirmCloseScreen { align: center middle; }
    #confirm-close-box {
        width: 58;
        max-width: 95%;
        height: auto;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #confirm-close-box Label { width: 1fr; height: auto; margin-bottom: 1; }
    #confirm-close-buttons { height: auto; align-horizontal: right; }
    #confirm-close-buttons Button { margin-left: 1; }
    """

    def __init__(self, warning: str, *, confirm_label: str = "Close session") -> None:
        super().__init__()
        self.warning = warning
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-close-box"):
            yield Label(self.warning, markup=False)
            with Horizontal(id="confirm-close-buttons"):
                yield Button("Cancel", id="close-cancel")
                yield Button(self.confirm_label, id="close-confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#close-cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "close-confirm")
