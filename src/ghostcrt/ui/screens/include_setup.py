from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from ghostcrt.config.include_bootstrap import add_include, include_line


class IncludeSetupModal(ModalScreen[bool]):
    """Offer to add the one Include line ghostcrt needs.

    This is the single exception to never writing ~/.ssh/config: one line, at
    the user's request, with a backup taken first.
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Later")]

    DEFAULT_CSS = """
    IncludeSetupModal { align: center middle; }
    #include-box {
        width: 66;
        height: auto;
        border: heavy $warning;
        padding: 1 2;
        background: $surface;
        &:ansi { background: $ansi-background; }
    }
    #include-line { color: $accent; padding: 1 0; }
    #include-error { color: $error; }
    """

    def __init__(self, ssh_config: Path, includes: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ssh_config = ssh_config
        self.includes = includes

    def compose(self) -> ComposeResult:
        with Vertical(id="include-box"):
            yield Label("Setup needed")
            yield Static(
                f"ghostcrt needs one line at the top of {self.ssh_config}.\n"
                "Groups will not apply until it is there."
            )
            yield Static(include_line(self.includes), id="include-line")
            yield Static(f"A backup will be written to {self.ssh_config}.bak first.")
            yield Static("", id="include-error")
            with Horizontal():
                yield Button("Add it for me", id="include-add", variant="primary")
                yield Button("Later", id="include-later")

    @on(Button.Pressed, "#include-add")
    def add(self) -> None:
        try:
            add_include(self.ssh_config, self.includes)
        except OSError as exc:
            self.query_one("#include-error", Static).update(f"Failed: {exc}")
            return
        self.dismiss(True)

    @on(Button.Pressed, "#include-later")
    def later(self) -> None:
        self.dismiss(False)
