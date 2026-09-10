from __future__ import annotations

from collections.abc import Awaitable
from typing import ClassVar

from ghostty_textual import TerminalTheme, TerminalView
from rich.color_triplet import ColorTriplet
from rich.terminal_theme import TerminalTheme as RichTerminalTheme
from textual import events
from textual.binding import Binding
from textual.color import Color
from textual.message import Message
from textual.theme import Theme

from ghostcrt.ssh.session import SshSession

# Keys owned by application/screen bindings. TerminalView leaves reserved key
# events untouched so Textual can route them to the appropriate binding.
_APP_KEYS = frozenset(
    {
        "ctrl+h",
        "ctrl+n",
        "ctrl+o",
        "ctrl+p",
        "ctrl+q",
        "ctrl+w",
        "ctrl+right_square_bracket",
    }
)


def _triplet(rgb: ColorTriplet) -> tuple[int, int, int]:
    return (rgb.red, rgb.green, rgb.blue)


def _resolve_theme_color(
    value: str,
    ansi_theme: RichTerminalTheme,
    default: ColorTriplet,
) -> tuple[int, int, int]:
    """Resolve a Textual CSS colour through its active ANSI palette."""
    color = Color.parse(value)
    triplet = color.rich_color.triplet
    if triplet is not None:
        return _triplet(triplet)
    if color.ansi is not None and color.ansi >= 0:
        return _triplet(ansi_theme.ansi_colors[color.ansi])
    return _triplet(default)


def terminal_theme_from_textual(
    theme: Theme,
    ansi_theme: RichTerminalTheme,
) -> TerminalTheme:
    """Translate Textual's resolved theme colours into a Ghostty theme."""
    variables = theme.to_color_system().generate()
    foreground = _resolve_theme_color(
        variables["foreground"],
        ansi_theme,
        ansi_theme.foreground_color,
    )
    background = _resolve_theme_color(
        variables["background"],
        ansi_theme,
        ansi_theme.background_color,
    )
    cursor = _resolve_theme_color(
        variables["block-cursor-background"],
        ansi_theme,
        ansi_theme.foreground_color,
    )
    ansi_palette = tuple(_triplet(ansi_theme.ansi_colors[index]) for index in range(16))
    palette = ansi_palette + TerminalTheme().palette[16:]
    return TerminalTheme(
        foreground=foreground,
        background=background,
        cursor=cursor,
        palette=palette,
    )


class TerminalWidget(TerminalView):
    """Bind ghostty-textual's transport-neutral widget to an SSH session."""

    DEFAULT_CSS = """
    TerminalWidget {
        height: 1fr;
        width: 1fr;
        background: $background;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding(
            "ctrl+right_square_bracket",
            "release_focus",
            "Release terminal",
            key_display="Ctrl+]",
            priority=True,
        )
    ]

    class ReleaseFocus(Message):
        """Request that the screen move focus outside the SSH terminal."""

    def __init__(self, session: SshSession, **kwargs) -> None:
        self.session = session
        super().__init__(
            send=self._send_session,
            resize_transport=self._resize_session,
            scrollback=session.history_size,
            reserved_keys=_APP_KEYS,
            **kwargs,
        )
        session.on_output = self.feed

    def on_mount(self) -> None:
        super().on_mount()
        self.app.theme_changed_signal.subscribe(self, self._apply_textual_theme)
        self._apply_textual_theme(self.app.current_theme)

    def _apply_textual_theme(self, theme: Theme) -> None:
        ansi_theme = self.app.ansi_theme_dark if theme.dark else self.app.ansi_theme_light
        self.terminal.set_theme(terminal_theme_from_textual(theme, ansi_theme))
        self.refresh_frame(force=True)

    def _send_session(self, data: bytes) -> Awaitable[None]:
        return self.session.send(data)

    def _resize_session(self, cols: int, rows: int) -> None:
        self.session.resize(rows, cols)

    def sync_pty_size(self) -> None:
        """Compatibility name used while mounting a new session tab."""
        self.sync_terminal_size()

    async def reset_session(self) -> None:
        """Discard stale writes and terminal state before a reconnect."""
        await self.reset_io()
        self.hard_reset()

    async def on_unmount(self) -> None:
        if self.session.on_output == self.feed:
            self.session.on_output = None
        self.app.theme_changed_signal.unsubscribe(self)
        await super().on_unmount()

    def action_release_focus(self) -> None:
        self.post_message(self.ReleaseFocus())

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.focus()
        super().on_mouse_down(event)
