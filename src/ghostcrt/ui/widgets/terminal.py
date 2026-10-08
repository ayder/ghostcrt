from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import ClassVar

from ghostty_textual import (
    Frame,
    GhosttyError,
    ScrollDelta,
    ScrollToRow,
    TerminalTheme,
    TerminalView,
    ViewportState,
)
from rich.color_triplet import ColorTriplet
from rich.terminal_theme import TerminalTheme as RichTerminalTheme
from textual import events
from textual.binding import Binding
from textual.color import Color
from textual.message import Message
from textual.theme import Theme
from textual.timer import Timer

from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession
from ghostcrt.vault.snippets import snippet_keystrokes

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
        "ctrl+t",
    }
)

# Keys that pick a snippet slot after Ctrl+N.
_SNIPPET_KEYS = frozenset("12345")


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
            "ctrl+t",
            "release_focus",
            "Release terminal",
            key_display="Ctrl+T",
            priority=True,
        )
    ]

    class ReleaseFocus(Message):
        """Request that the screen move focus outside the SSH terminal."""

    class SnippetArmed(Message):
        """Ctrl+N was pressed here; the next key picks a snippet slot."""

    class SnippetChosen(Message):
        """The key after Ctrl+N was handled.

        `slot` is the chosen slot, or None when cancelled. `outcome` is
        "typed", "empty", "not-connected" or "cancelled".
        """

        def __init__(self, slot: int | None, outcome: str) -> None:
            super().__init__()
            self.slot = slot
            self.outcome = outcome

    class ViewportChanged(Message):
        """Keep the pane's scrollbar in sync with the emulator."""

        def __init__(self, viewport: ViewportState, rows: int) -> None:
            super().__init__()
            self.viewport = viewport
            self.rows = rows

    def __init__(
        self,
        session: SshSession,
        *,
        snippet_text: Callable[[int], str | None] | None = None,
        **kwargs,
    ) -> None:
        self.session = session
        self.snippet_text = snippet_text
        self._frame_timer: Timer | None = None
        self.snippet_armed = False
        super().__init__(
            send=self._send_session,
            resize_transport=self._resize_session,
            scrollback=session.history_size,
            reserved_keys=_APP_KEYS,
            **kwargs,
        )
        session.on_output = self.feed

    def refresh_frame(self, *, force: bool = False) -> None:
        # Coalesce output and scrolling across event-loop turns. Upstream feed
        # batching alone does not cap sustained output or trackpad redraws.
        if self.failed:
            return
        if force:
            self._cancel_frame_timer()
            super().refresh_frame(force=True)
        elif self._mounted_ready and self._frame_timer is None:
            self._frame_timer = self.set_timer(1 / 60, self._flush_throttled_frame)

    def _cancel_frame_timer(self) -> None:
        if self._frame_timer is not None:
            self._frame_timer.stop()
            self._frame_timer = None

    def _flush_throttled_frame(self) -> None:
        # Keep this distinct from TerminalView's deferred feed callback, which
        # must reach our refresh_frame override before extracting a snapshot.
        self._frame_timer = None
        if self._mounted_ready:
            super().refresh_frame()

    def _apply_frame(self, frame: Frame) -> set[int]:
        changed = super()._apply_frame(frame)
        self.post_message(self.ViewportChanged(frame.viewport, frame.rows))
        return changed

    def scroll_history(self, request: ScrollDelta | ScrollToRow) -> None:
        if self.failed:
            return
        try:
            self.terminal.scroll_viewport(request)
            self.refresh_frame()
        except GhosttyError as exc:
            self._fail(exc)

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

    def arm_snippet(self) -> None:
        """Take the next key as a snippet slot instead of sending it."""
        self.snippet_armed = True

    async def on_key(self, event: events.Key) -> None:
        # Textual runs TerminalView.on_key after this handler unless the default
        # is prevented, so do not call super(): other keys reach it anyway.
        # Ctrl+N and the slot key are handled here, not by screen bindings, so
        # keys that arrive in the same read wait their turn behind the snippet.
        if not self.snippet_armed and event.key != "ctrl+n":
            return
        event.stop()
        event.prevent_default()
        if not self.snippet_armed:
            self.arm_snippet()
            self.post_message(self.SnippetArmed())
        elif event.key in _SNIPPET_KEYS:
            slot = int(event.key)
            self.post_message(self.SnippetChosen(slot, await self.type_snippet(slot)))
        else:
            self.snippet_armed = False
            self.post_message(self.SnippetChosen(None, "cancelled"))

    def on_blur(self) -> None:
        if self.snippet_armed:
            self.snippet_armed = False
            self.post_message(self.SnippetChosen(None, "cancelled"))

    async def type_snippet(self, slot: int) -> str:
        """Disarm and type a stored snippet: "typed", "empty" or "not-connected"."""
        self.snippet_armed = False
        text = self.snippet_text(slot) if self.snippet_text is not None else None
        if text is None:
            return "empty"
        return "typed" if await self.type_text(text) else "not-connected"

    async def type_text(self, text: str) -> bool:
        """Type snippet text as keystrokes; False when the session cannot take input."""
        if self.failed or self.session.state != SessionState.CONNECTED:
            return False
        try:
            await self._enqueue(snippet_keystrokes(text))
        except GhosttyError as exc:
            self._fail(exc)
            return False
        return True

    async def on_paste(self, event: events.Paste) -> None:
        event.stop()
        event.prevent_default()
        if self.failed:
            return
        try:
            text = event.text
            if not self.terminal.modes.bracketed_paste:
                # Ordinary terminal input uses CR for Enter. Normalize CRLF
                # first to avoid submitting Windows line endings twice.
                # ghostty-textual rejects LF before its encoder can do this.
                text = text.replace("\r\n", "\n").replace("\n", "\r")
            encoded = self.terminal.encode_paste(text)
            if encoded is not None:
                await self._enqueue(encoded)
            else:
                self.post_message(self.PasteRejected(event.text))
                self.notify("The terminal rejected this paste.", severity="warning")
        except GhosttyError as exc:
            self._fail(exc)

    def _resize_session(self, cols: int, rows: int) -> None:
        self.session.resize(rows, cols)

    def sync_pty_size(self) -> None:
        """Compatibility name used while mounting a new session tab."""
        self.sync_terminal_size()

    async def reset_session(self) -> None:
        """Discard stale writes and terminal state before a reconnect."""
        self._cancel_frame_timer()
        await self.reset_io()
        self.hard_reset()

    async def on_unmount(self) -> None:
        self._cancel_frame_timer()
        if self.session.on_output == self.feed:
            self.session.on_output = None
        self.app.theme_changed_signal.unsubscribe(self)
        await super().on_unmount()

    def action_release_focus(self) -> None:
        self.post_message(self.ReleaseFocus())

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.focus()
        super().on_mouse_down(event)
