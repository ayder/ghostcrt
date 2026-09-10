import tempfile
from pathlib import Path

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
    return session, pilot.app.screen.query_one(TerminalWidget)


async def test_ctrl_close_bracket_releases_terminal_focus():
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

        await pilot.press("ctrl+right_square_bracket")

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


async def test_terminal_renderer_preserves_ansi_and_truecolor_styles():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "styles")
        feed(session, "\x1b[91;48;2;1;2;3;1mX")
        await pilot.pause()

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
        await pilot.pause()

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
        await pilot.pause()

        result = terminal.get_selection(Selection(Offset(1, 0), Offset(4, 1)))

        assert result == ("ello\nworl", "\n")
        await session.close()


async def test_get_selection_drops_the_blank_padding_of_terminal_rows():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "padding")
        feed(session, "hi")
        await pilot.pause()

        text, _ = terminal.get_selection(Selection(Offset(0, 0), Offset(60, 0)))

        assert text == "hi"
        await session.close()


async def test_render_line_tags_offsets_so_clicks_map_to_characters():
    app = TerminalTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        session, terminal = await open_terminal(pilot, "offsets")
        feed(session, "abc")
        await pilot.pause()

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
        await pilot.pause()

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
