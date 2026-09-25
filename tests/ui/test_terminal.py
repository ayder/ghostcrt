import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from textual import events
from textual.app import App
from textual.geometry import Offset
from textual.selection import Selection

from ghostcrt.config.inventory import HostInventory
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostList
from ghostcrt.ui.widgets.session_tabs import SessionTabs
from ghostcrt.ui.widgets.terminal import TerminalWidget
from ghostcrt.ui.widgets.terminal_pane import TerminalPane

# What Vim/htop emit to request SGR any-event mouse tracking.
REMOTE_ENABLES_MOUSE = "\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h"


class FakeVault:
    def get(self, alias: str) -> None:
        return None


def scratch_inventory() -> HostInventory:
    """A throwaway inventory holding one host, for screens that just need one."""
    root = Path(tempfile.mkdtemp())
    cfg = root / "config"
    includes = root / "includes"
    includes.mkdir()
    (includes / "example.conf").write_text("Host example\n")
    cfg.write_text(f"Include {includes}/*\n")
    return HostInventory(cfg, includes)


class TerminalTestApp(App[None]):
    def on_mount(self) -> None:
        self.push_screen(MainScreen(FakeVault(), scratch_inventory()))


def feed(session: SshSession, text: str) -> None:
    """Deliver remote output exactly the way SshSession._pump does."""
    session._notify_output(text.encode())


def record_pty_writes(session: SshSession) -> list[bytes]:
    """Capture everything the widget tries to write to the remote process."""
    sent: list[bytes] = []

    async def _send(data: bytes) -> None:
        sent.append(data)

    session.send = _send  # type: ignore[method-assign]
    return sent


def scroll_event(terminal: TerminalWidget, up: bool) -> events.MouseEvent:
    cls = events.MouseScrollUp if up else events.MouseScrollDown
    return cls(
        widget=terminal,
        x=1,
        y=1,
        delta_x=0,
        delta_y=-1 if up else 1,
        button=0,
        shift=False,
        meta=False,
        ctrl=False,
        screen_x=1,
        screen_y=1,
    )


async def open_terminal(pilot, alias: str) -> tuple[SshSession, TerminalWidget]:
    session = SshSession(alias)
    await pilot.app.screen.query_one(SessionTabs).add_session(session)
    await pilot.pause()
    terminal = pilot.app.screen.query_one(TerminalWidget)
    await wait_for_frame(pilot, terminal)
    return session, terminal


async def wait_for_frame(pilot, terminal: TerminalWidget) -> None:
    """Wait for deferred rendering and its scrollbar message, not just CPU idle."""
    async with asyncio.timeout(2):
        # Dispatch queued wheel/key events before checking their pending frame.
        await pilot.pause()
        while terminal._frame_timer is not None:
            await asyncio.sleep(0.005)
        # The frame callback posts ViewportChanged; let the pane consume it.
        await pilot.pause()


async def test_ctrl_t_releases_terminal_focus():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.screen.query_one(SessionTabs)
        session = SshSession("example")
        await tabs.add_session(session)
        terminal = app.screen.query_one(TerminalWidget)
        await pilot.pause()
        terminal.focus()
        await pilot.pause()
        assert app.focused is terminal

        await pilot.press("ctrl+t")

        assert app.focused is app.screen.query_one(HostList).query_one("#host-tree")
        await session.close()


async def test_tabs_reject_new_sessions_during_app_shutdown():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.screen.query_one(SessionTabs)
        await tabs.close_all()

        with pytest.raises(RuntimeError, match="closing"):
            await tabs.add_session(SshSession("too-late"))


@pytest.mark.parametrize("size", [(120, 40), (80, 24)])
async def test_tab_layout_sets_session_size_before_process_start(size):
    app = TerminalTestApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        session = SshSession("sized")
        await app.screen.query_one(SessionTabs).add_session(session)
        terminal = app.screen.query_one(TerminalWidget)

        assert terminal.content_size.height > 0
        assert session._rows == terminal.content_size.height
        assert session._cols == terminal.content_size.width
        assert not terminal.styles.outline

        await session.close()


@pytest.mark.parametrize("frame_delay", [1 / 60, 0.1], ids=["normal", "delayed-timer"])
async def test_terminal_renderer_preserves_ansi_and_truecolor_styles(monkeypatch, frame_delay):
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "styles")
        set_timer = terminal.set_timer

        def delayed_timer(delay, callback=None, **kwargs):
            if callback == terminal._flush_frame:
                delay = frame_delay
            return set_timer(delay, callback, **kwargs)

        monkeypatch.setattr(terminal, "set_timer", delayed_timer)
        feed(session, "\x1b[91;48;2;1;2;3;1mX")
        await wait_for_frame(pilot, terminal)

        segment = terminal.render_line(0)._segments[0]
        style = segment.style

        assert style is not None
        assert style.color is not None
        assert tuple(style.color.triplet) == terminal.terminal.theme.palette[9]
        assert style.bgcolor is not None and style.bgcolor.triplet.hex == "#010203"
        assert style.bold
        await session.close()


async def test_terminal_inherits_the_active_textual_theme():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        app.theme = "monokai"
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "themed")

        theme = terminal.terminal.theme
        assert theme.foreground == (214, 214, 214)
        assert theme.background == (39, 40, 34)
        assert theme.cursor == (174, 129, 255)
        assert theme.palette[0] == (26, 26, 26)
        assert len(theme.palette) == 256
        await session.close()


async def test_open_terminal_updates_when_the_textual_theme_changes():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        app.theme = "monokai"
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "theme-switch")
        feed(session, "X")
        await wait_for_frame(pilot, terminal)

        app.theme = "textual-light"
        await pilot.pause()
        await pilot.pause()

        theme = terminal.terminal.theme
        assert theme.foreground == (31, 31, 31)
        assert theme.background == (224, 224, 224)
        assert theme.cursor == (0, 69, 120)
        assert theme.palette[0] == (0, 0, 0)
        style = terminal.render_line(0)._segments[0].style
        assert style is not None
        assert style.color is not None and tuple(style.color.triplet) == theme.foreground
        assert style.bgcolor is not None and tuple(style.bgcolor.triplet) == theme.background
        await session.close()


async def test_terminal_query_reply_uses_the_session_transport():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, _terminal = await open_terminal(pilot, "query")
        sent = record_pty_writes(session)

        feed(session, "\x1b[6n")
        await pilot.pause()

        assert sent == [b"\x1b[1;1R"]
        await session.close()


async def test_wheel_scrolls_local_history_even_when_remote_app_enables_mouse_mode():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "wheel")
        feed(session, "".join(f"line {index}\r\n" for index in range(40)))
        feed(session, REMOTE_ENABLES_MOUSE)
        sent = record_pty_writes(session)

        terminal.post_message(scroll_event(terminal, up=True))
        await pilot.pause()

        assert sent == []
        assert not terminal.terminal.viewport.at_bottom
        await session.close()


async def test_press_and_drag_are_never_forwarded_to_the_remote_app():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "drag")
        feed(session, REMOTE_ENABLES_MOUSE)
        sent = record_pty_writes(session)

        await pilot.mouse_down(terminal, offset=(2, 1))
        await pilot.hover(terminal, offset=(6, 1))
        await pilot.mouse_up(terminal, offset=(6, 1))
        await pilot.pause()

        assert sent == []


async def test_terminal_never_captures_the_mouse_so_selection_can_start():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "capture")
        feed(session, REMOTE_ENABLES_MOUSE)

        await pilot.mouse_down(terminal, offset=(2, 1))
        await pilot.pause()

        assert app.mouse_captured is None
        await pilot.mouse_up(terminal, offset=(2, 1))
        await session.close()


async def test_clicking_the_terminal_still_focuses_it():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "focus")

        await pilot.click(terminal, offset=(2, 1))
        await pilot.pause()

        assert app.focused is terminal
        await session.close()


async def test_get_selection_extracts_text_from_the_visible_screen():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "select")
        feed(session, "hello\r\nworld")
        await wait_for_frame(pilot, terminal)

        result = terminal.get_selection(Selection(Offset(1, 0), Offset(4, 1)))

        assert result == ("ello\nworl", "\n")
        await session.close()


async def test_get_selection_drops_the_blank_padding_of_terminal_rows():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "padding")
        feed(session, "hi")
        await wait_for_frame(pilot, terminal)

        text, _ = terminal.get_selection(Selection(Offset(0, 0), Offset(60, 0)))

        assert text == "hi"
        await session.close()


async def test_render_line_tags_offsets_so_clicks_map_to_characters():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "offsets")
        feed(session, "abc")
        await wait_for_frame(pilot, terminal)

        offsets = [
            segment.style.meta.get("offset")
            for segment in terminal.render_line(0)
            if segment.style is not None
        ]

        assert (0, 0) in offsets
        await session.close()


async def test_render_line_highlights_the_selected_span():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "highlight")
        feed(session, "abcdef")
        await wait_for_frame(pilot, terminal)

        plain = terminal.render_line(0)
        terminal._selection_anchor = (1, 0)
        terminal._selection_end = (3, 0)
        highlighted = terminal.render_line(0)

        assert highlighted != plain
        styles = [
            segment.style for segment in highlighted.divide([1, 3])[1] if segment.style is not None
        ]
        assert styles
        assert all(style.reverse for style in styles)
        await session.close()


async def test_wheel_burst_extracts_one_frame_and_keeps_the_final_position(monkeypatch):
    app = TerminalTestApp()
    async with app.run_test(size=(240, 70)) as pilot:
        session, terminal = await open_terminal(pilot, "scroll-burst")
        feed(session, "".join(f"line {index}\r\n" for index in range(1000)))
        await wait_for_frame(pilot, terminal)
        before = terminal.terminal.viewport.offset
        snapshot = Mock(wraps=terminal.terminal.snapshot)
        monkeypatch.setattr(terminal.terminal, "snapshot", snapshot)

        for _ in range(100):
            terminal.on_mouse_scroll_up(scroll_event(terminal, up=True))

        assert snapshot.call_count == 0
        assert terminal.terminal.viewport.offset == max(0, before - 300)
        await wait_for_frame(pilot, terminal)
        assert snapshot.call_count == 1
        frame = terminal.terminal.snapshot(force=True)
        assert frame is not None
        assert terminal._shadow.rows == tuple(patch.cells for patch in frame.row_patches)


async def test_output_burst_batches_frames_without_delaying_terminal_replies(monkeypatch):
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "output-burst")
        sent = record_pty_writes(session)
        snapshot = Mock(wraps=terminal.terminal.snapshot)
        monkeypatch.setattr(terminal.terminal, "snapshot", snapshot)

        for _ in range(100):
            feed(session, "line\r\n")
        feed(session, "LATEST\x1b[5n")

        assert snapshot.call_count == 0
        assert terminal._queue is not None and terminal._queue.qsize() == 1
        await wait_for_frame(pilot, terminal)
        assert snapshot.call_count == 1
        assert sent == [b"\x1b[0n"]
        assert terminal.render_line(terminal.terminal.rows - 1).text.startswith("LATEST")


async def test_scrollbar_tracks_history_and_supports_drag_and_track_clicks():
    app = TerminalTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        session, terminal = await open_terminal(pilot, "scrollbar")
        pane = terminal.parent
        assert isinstance(pane, TerminalPane)
        bar = pane.history_scrollbar
        original_size = (session._cols, session._rows)
        feed(session, "".join(f"line {index}\r\n" for index in range(300)))
        await wait_for_frame(pilot, terminal)

        viewport = terminal.terminal.viewport
        assert bar.region.width == 1
        assert bar.region.x == terminal.region.right
        assert bar.window_virtual_size == viewport.total_rows
        assert bar.window_size == terminal.terminal.rows
        assert bar.position == viewport.offset > 0
        assert (session._cols, session._rows) == original_size

        terminal.post_message(scroll_event(terminal, up=True))
        await wait_for_frame(pilot, terminal)
        assert bar.position == viewport.offset - 3

        # Drag the handle from the bottom to the top using real mouse events.
        await pilot.mouse_down(bar, offset=(0, bar.size.height - 1))
        assert app.mouse_captured is bar
        await pilot.hover(bar, offset=(0, 0))
        await pilot.mouse_up(bar, offset=(0, 0))
        await wait_for_frame(pilot, terminal)
        assert app.mouse_captured is None
        assert bar.position == terminal.terminal.viewport.offset == 0

        await pilot.click(bar, offset=(0, bar.size.height - 1))
        await wait_for_frame(pilot, terminal)
        assert bar.position == terminal.terminal.rows - 1
        assert bar.position == terminal.terminal.viewport.offset


async def test_scrollbar_restores_primary_history_after_alternate_screen_and_reset():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "screen-switch")
        pane = terminal.parent
        assert isinstance(pane, TerminalPane)
        bar = pane.history_scrollbar
        feed(session, "line\r\n" * 200)
        await wait_for_frame(pilot, terminal)
        primary_total = bar.window_virtual_size

        feed(session, "\x1b[?1049h")
        await wait_for_frame(pilot, terminal)
        assert bar.window_virtual_size == bar.window_size
        assert bar.position == 0

        feed(session, "\x1b[?1049l")
        await wait_for_frame(pilot, terminal)
        assert bar.window_virtual_size == primary_total
        assert bar.position == terminal.terminal.viewport.offset

        feed(session, "pending frame")
        assert terminal._frame_timer is not None
        await terminal.reset_session()
        await pilot.pause()
        assert terminal._frame_timer is None
        assert bar.window_virtual_size == bar.window_size
        assert bar.position == 0
        assert "pending frame" not in terminal.render_line(0).text


async def test_closing_terminal_cancels_pending_frame():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "closing-frame")
        feed(session, "pending")
        assert terminal._frame_timer is not None
        await app.screen.query_one(SessionTabs).close_active()
        await pilot.pause()
        assert terminal._frame_timer is None
        assert terminal.terminal.closed


@pytest.mark.parametrize(
    "text,expected",
    [
        ("one line", b"one line"),
        ("first\nsecond", b"first\rsecond"),
        ("first\r\nsecond\r\n", b"first\rsecond\r"),
        ("first\rsecond", b"first\rsecond"),
        ("first\n\n\tlast\n", b"first\r\r\tlast\r"),
        ("Türkçe\n日本語", "Türkçe\r日本語".encode()),
        ("line\n" * 15000, b"line\r" * 15000),
    ],
    ids=["single", "multiline", "windows", "cr", "blank-lines", "unicode", "large"],
)
async def test_paste_without_bracketed_mode_sends_all_lines_once(text, expected):
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "paste")
        sent = record_pty_writes(session)
        assert not terminal.terminal.modes.bracketed_paste

        terminal.post_message(events.Paste(text))
        await pilot.pause()

        assert sent == [expected]
        assert not terminal.failed


async def test_bracketed_paste_preserves_multiline_text_and_tracks_mode_changes():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "bracketed-paste")
        sent = record_pty_writes(session)
        text = "first\n\tsecond\r\nlast"
        feed(session, "\x1b[?2004h")
        terminal.post_message(events.Paste(text))
        await pilot.pause()
        assert sent == [b"\x1b[200~" + text.encode() + b"\x1b[201~"]

        feed(session, "\x1b[?2004l")
        terminal.post_message(events.Paste(text))
        await pilot.pause()
        assert sent[-1] == b"first\r\tsecond\rlast"
        assert len(sent) == 2


async def test_multiline_paste_still_uses_ghostty_control_character_filtering():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "paste-filter")
        sent = record_pty_writes(session)
        terminal.post_message(events.Paste("first\n\x03\x1blast"))
        await pilot.pause()
        assert sent == [b"first\r  last"]


async def test_rejected_paste_notifies_without_echoing_clipboard_contents(monkeypatch):
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "rejected-paste")
        sent = record_pty_writes(session)
        notify = Mock()
        monkeypatch.setattr(terminal, "notify", notify)
        terminal.post_message(events.Paste("private-clipboard\x1b[201~"))
        await pilot.pause()
        assert sent == []
        notify.assert_called_once_with("The terminal rejected this paste.", severity="warning")


async def test_multiline_paste_reaches_a_real_pty_process():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        session, terminal = await open_terminal(pilot, "paste-pty")
        output = bytearray()

        def receive(data: bytes) -> None:
            output.extend(data)
            terminal.feed(data)

        session.on_output = receive
        try:
            await session.start(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "data = b''.join(sys.stdin.buffer.readline() for _ in range(3)); "
                        "print('RECEIVED:' + data.hex(), flush=True)"
                    ),
                ]
            )
            terminal.post_message(events.Paste("first\r\nsecond\nTürkçe\n"))
            assert session._pump_task is not None
            await asyncio.wait_for(asyncio.shield(session._pump_task), timeout=5)

            expected = "first\nsecond\nTürkçe\n".encode().hex()
            assert f"RECEIVED:{expected}".encode() in output
            assert session.exit_code == 0
        finally:
            await session.close()
