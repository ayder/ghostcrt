from __future__ import annotations

from ghostty_textual import ScrollDelta, ScrollToRow
from textual import events, on
from textual.containers import Horizontal
from textual.scrollbar import ScrollBar, ScrollDown, ScrollTo, ScrollUp

from ghostcrt.ui.widgets.terminal import TerminalWidget


class TerminalPane(Horizontal):
    """A terminal viewport and a scrollbar over Ghostty's own history."""

    DEFAULT_CSS = """
    TerminalPane {
        height: 1fr;
        width: 1fr;
        overflow: hidden hidden;
    }
    TerminalPane > ScrollBar {
        width: 1;
        height: 1fr;
    }
    """

    def __init__(self, terminal: TerminalWidget) -> None:
        self.terminal_view = terminal
        self.history_scrollbar = ScrollBar()
        # Reserve a column even without history, avoiding PTY resizes/reflow
        # whenever output creates or clears scrollback.
        super().__init__(terminal, self.history_scrollbar)

    @on(TerminalWidget.ViewportChanged)
    def update_scrollbar(self, message: TerminalWidget.ViewportChanged) -> None:
        message.stop()
        bar = self.history_scrollbar
        bar.window_virtual_size = message.viewport.total_rows
        bar.window_size = message.rows
        bar.position = message.viewport.offset

    def on_scroll_to(self, message: ScrollTo) -> None:
        message.stop()
        message.prevent_default()
        if message.y is not None:
            bar = self.history_scrollbar
            maximum = max(0, bar.window_virtual_size - bar.window_size)
            self.terminal_view.scroll_history(ScrollToRow(max(0, min(maximum, round(message.y)))))

    def on_scroll_up(self, message: ScrollUp) -> None:
        message.stop()
        message.prevent_default()
        self.terminal_view.scroll_history(
            ScrollDelta(-max(1, self.history_scrollbar.window_size - 1))
        )

    def on_scroll_down(self, message: ScrollDown) -> None:
        message.stop()
        message.prevent_default()
        self.terminal_view.scroll_history(
            ScrollDelta(max(1, self.history_scrollbar.window_size - 1))
        )

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.prevent_default()
        self.terminal_view.on_mouse_scroll_up(event)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.prevent_default()
        self.terminal_view.on_mouse_scroll_down(event)
