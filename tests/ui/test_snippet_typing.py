import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Input

from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.widgets.terminal import TerminalWidget


class TypingApp(App[None]):
    """A bare terminal plus one other focusable widget; no MainScreen."""

    def __init__(self, session: SshSession) -> None:
        super().__init__()
        self.session = session
        self.chosen: list[int | None] = []

    def compose(self) -> ComposeResult:
        yield TerminalWidget(self.session, id="terminal")
        yield Input(id="elsewhere")

    # Unannotated on purpose: an annotation naming TerminalWidget.SnippetChosen
    # would fail at import before the message exists, hiding the RED failures.
    def on_terminal_widget_snippet_chosen(self, message) -> None:
        self.chosen.append(message.slot)


def connected_session() -> tuple[SshSession, list[bytes]]:
    session = SshSession("synthetic-host")
    session.state = SessionState.CONNECTED
    sent: list[bytes] = []

    async def record(data: bytes) -> None:
        sent.append(data)

    session.send = record  # type: ignore[method-assign]
    return session, sent


async def settle(pilot) -> None:
    """Let the widget's input queue hand its bytes to the session."""
    for _ in range(3):
        await pilot.pause()
    await asyncio.sleep(0.01)


async def focused_terminal(pilot) -> TerminalWidget:
    terminal = pilot.app.query_one(TerminalWidget)
    terminal.focus()
    await pilot.pause()
    return terminal


async def test_type_text_sends_lines_as_enter_presses():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        assert await terminal.type_text("cd /srv\nşifre\\n") is True
        await settle(pilot)

        assert b"".join(sent) == "cd /srv\rşifre\r".encode()


async def test_type_text_ignores_bracketed_paste_mode():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)
        session._notify_output(b"\x1b[?2004h")  # remote shell enables bracketed paste
        await settle(pilot)
        assert terminal.terminal.modes.bracketed_paste

        await terminal.type_text("ls\\n")
        await settle(pilot)

        assert b"".join(sent) == b"ls\r"


async def test_type_text_sends_a_full_size_snippet():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        await terminal.type_text("x" * 4096)
        await settle(pilot)

        assert b"".join(sent) == b"x" * 4096


async def test_type_text_refuses_a_session_that_is_not_connected():
    session, sent = connected_session()
    session.state = SessionState.DISCONNECTED
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        assert await terminal.type_text("pw\\n") is False
        await settle(pilot)

        assert sent == []


async def test_armed_digit_chooses_its_slot_and_is_not_sent():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        terminal.arm_snippet()
        await pilot.press("2")
        await settle(pilot)

        assert app.chosen == [2]
        assert sent == []
        assert terminal.snippet_armed is False


async def test_armed_other_key_cancels_and_next_key_reaches_session():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        terminal.arm_snippet()
        await pilot.press("x")
        await settle(pilot)
        assert app.chosen == [None]
        assert sent == []

        await pilot.press("x")
        await settle(pilot)
        assert b"".join(sent) == b"x"


async def test_armed_escape_cancels_without_sending():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        terminal.arm_snippet()
        await pilot.press("escape")
        await settle(pilot)

        assert app.chosen == [None]
        assert sent == []
        assert app.focused is terminal


async def test_moving_focus_cancels_snippet_mode():
    session, _sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        terminal = await focused_terminal(pilot)

        terminal.arm_snippet()
        app.query_one("#elsewhere").focus()
        await settle(pilot)

        assert app.chosen == [None]
        assert terminal.snippet_armed is False


async def test_unarmed_digit_is_typed_normally():
    session, sent = connected_session()
    app = TypingApp(session)
    async with app.run_test() as pilot:
        await focused_terminal(pilot)

        await pilot.press("2")
        await settle(pilot)

        assert app.chosen == []
        assert b"".join(sent) == b"2"
