from __future__ import annotations

import traceback
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App
from textual.binding import Binding

from ghostcrt.config.inventory import HostInventory
from ghostcrt.config.paths import (
    ensure_config_dir,
    ensure_includes_dir,
    ssh_config_path,
    vault_path,
)
from ghostcrt.config.settings import load_settings, save_settings
from ghostcrt.models import AppSettings
from ghostcrt.ui.mouse import toggle_mouse_capture
from ghostcrt.ui.screens.help import HelpScreen
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.screens.unlock import UnlockScreen
from ghostcrt.ui.widgets.session_tabs import SessionTabs
from ghostcrt.vault.vault import Vault


class GhostCRTApp(App[None]):
    TITLE = "ghostcrt"
    BINDINGS: ClassVar[list[Binding | tuple[str, str, str]]] = [
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+p", "command_palette", "Palette", show=False, priority=True),
        Binding(
            "ctrl+h",
            "toggle_help",
            "Help",
            key_display="ctrl+h",
            priority=True,
        ),
        # Not ctrl+m: a terminal sends that as carriage return, so Textual maps
        # it to Enter (Keys.ControlM) and binding it would eat the Return key.
        # This must be priority, or a focused TerminalWidget forwards ctrl+o to
        # the remote app instead of toggling mouse capture.
        Binding("ctrl+o", "toggle_mouse", "Mouse", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        ssh_config: Path | None = None,
        vault: Path | None = None,
        theme: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._ssh_config_path = ssh_config
        self._vault_path = vault
        self._theme_override = theme
        self._settings = AppSettings()
        self.vault: Vault | None = None
        self.inventory: HostInventory | None = None

    def on_mount(self) -> None:
        ensure_config_dir()
        self._settings = load_settings()
        preferred = self._theme_override or self._settings.theme or "ansi-dark"
        if preferred == "textual-ansi":
            # Pre-8.2.5 placeholder used by early ghostcrt builds.
            preferred = "ansi-dark"
        if preferred not in self.available_themes:
            preferred = "textual-dark"
        self.theme = preferred
        if self._theme_override and self._theme_override in self.available_themes:
            self._settings.theme = self._theme_override
            save_settings(self._settings)

        vpath = self._vault_path or vault_path()
        self.push_screen(UnlockScreen(vpath), self._on_unlocked)

    def _on_unlocked(self, vault: Vault | None) -> None:
        if vault is None:
            self.exit()
            return
        self.vault = vault
        cfg = self._ssh_config_path or ssh_config_path()
        self.inventory = HostInventory(cfg, ensure_includes_dir())
        self.push_screen(MainScreen(vault, self.inventory, ssh_config=self._ssh_config_path))

    def _handle_exception(self, error: Exception) -> None:
        """Report crash locations without exception text, reprs, source, or locals.

        Textual's default renderer includes locals (and accepts arbitrary Rich
        exception renderers), which can expose decrypted passwords and keys.
        """
        self._return_code = 1
        if self._exception is None:
            self._exception = error
            self._exception_event.set()
        locations = "\n".join(
            f"  {frame.filename}:{frame.lineno} in {frame.name}"
            for frame in traceback.extract_tb(error.__traceback__)
        )
        self.exit(
            return_code=1,
            message=Text(
                f"ghostcrt stopped after an unexpected error ({type(error).__name__}).\n"
                f"{locations}\nError details are omitted to protect credentials."
            ),
        )

    def watch_theme(self, theme: str) -> None:
        # Persist theme changes from command palette
        if not hasattr(self, "_settings"):
            return
        if theme and theme != self._settings.theme:
            self._settings.theme = theme
            try:
                save_settings(self._settings)
            except OSError:
                pass

    def action_toggle_mouse(self) -> None:
        """Release the host terminal's mouse, or take it back."""
        captured = toggle_mouse_capture(self._driver)
        if captured is None:
            return
        if captured:
            self.notify(
                "Mouse captured: wheel scrolling, tab clicks and in-pane drag-select are back.",
                title="Mouse",
            )
        else:
            self.notify(
                "Mouse released to your terminal: use its native selection. ctrl+o takes it back.",
                title="Mouse",
            )

    def action_toggle_help(self) -> None:
        """Show the keyboard reference, or close it when it is already open."""
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss()
            return
        self.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        for screen in self.screen_stack:
            for tabs in screen.query(SessionTabs):
                await tabs.close_all()
        self.exit()
