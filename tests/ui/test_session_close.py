import sys
from typing import ClassVar

import pytest
from textual.app import App
from textual.widgets import Button, TabbedContent

from ghostcrt.app import GhostCRTApp
from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.confirm_close import ConfirmCloseScreen
from ghostcrt.ui.widgets.session_tab import SessionTab
from ghostcrt.ui.widgets.session_tabs import SessionTabs


class SessionApp(App):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("ctrl+w", "close_session", "Close")]
    action_quit = GhostCRTApp.action_quit

    def compose(self):
        yield SessionTabs()

    def action_close_session(self):
        self.query_one(SessionTabs).request_close_active()


async def click_close(pilot, tabs, pane_id):
    tab = tabs.query_one(TabbedContent).get_tab(pane_id)
    assert isinstance(tab, SessionTab)
    await pilot.click(tab, offset=(tab.size.width - 2, 0))
    await pilot.pause()


async def test_x_closes_exited_background_tab_without_switching_active_session():
    app = SessionApp()
    async with app.run_test(size=(120, 30)) as pilot:
        tabs = app.query_one(SessionTabs)
        exited = SshSession("exited")
        first = await tabs.add_session(exited)
        exited.exit_code = 7
        exited._set_state(SessionState.DISCONNECTED)
        live = SshSession("live")
        second = await tabs.add_session(live)
        await pilot.pause()

        first_tab = tabs.query_one(TabbedContent).get_tab(first)
        assert first_tab.label_text == "exited [exit 7]  ×"
        await click_close(pilot, tabs, first)

        assert not isinstance(app.screen, ConfirmCloseScreen)
        assert exited._disposed
        assert not live._disposed
        assert tabs.active_session is live
        assert tabs.query_one(TabbedContent).active == second
        assert len(tabs.query(SessionTab)) == 1


@pytest.mark.parametrize("state", [SessionState.CONNECTING, SessionState.CONNECTED])
async def test_x_on_live_background_tab_can_cancel_or_close_exact_session(state):
    app = SessionApp()
    async with app.run_test(size=(120, 30)) as pilot:
        tabs = app.query_one(SessionTabs)
        first_session = SshSession("first")
        first = await tabs.add_session(first_session)
        first_session._set_state(state)
        second_session = SshSession("second")
        await tabs.add_session(second_session)

        await click_close(pilot, tabs, first)
        assert isinstance(app.screen, ConfirmCloseScreen)
        assert app.screen.query_one("#close-cancel", Button).has_focus
        assert tabs.active_session is second_session
        await pilot.press("escape")
        assert not first_session._disposed

        await click_close(pilot, tabs, first)
        await pilot.click("#close-confirm")
        await pilot.pause()
        assert first_session._disposed
        assert not second_session._disposed
        assert tabs.active_session is second_session


async def test_tab_title_click_still_activates_tab_and_last_exited_tab_closes():
    app = SessionApp()
    async with app.run_test(size=(120, 30)) as pilot:
        tabs = app.query_one(SessionTabs)
        first_session = SshSession("first")
        first = await tabs.add_session(first_session)
        second = await tabs.add_session(SshSession("second"))
        await pilot.click(tabs.query_one(TabbedContent).get_tab(first), offset=(2, 0))
        assert tabs.active_session is first_session
        await tabs.close_session(second)
        first_session._set_state(SessionState.DISCONNECTED)
        await pilot.pause()
        await click_close(pilot, tabs, first)
        assert tabs.active_session is None
        assert not tabs.query(SessionTab)


async def test_ctrl_w_warns_and_confirmation_reaps_real_session_process():
    app = SessionApp()
    session = SshSession("local-process")
    try:
        async with app.run_test() as pilot:
            tabs = app.query_one(SessionTabs)
            await tabs.add_session(session)
            await session.start([sys.executable, "-c", "import time; time.sleep(60)"])
            proc = session._proc
            assert proc is not None
            await pilot.press("ctrl+w")
            assert isinstance(app.screen, ConfirmCloseScreen)
            await pilot.press("enter")  # Cancel is the default.
            assert not session._disposed
            await pilot.press("ctrl+w")
            await pilot.click("#close-confirm")
            await pilot.pause()
            assert session._disposed
            assert proc._closed and proc._exit_code is not None
    finally:
        await session.close()


async def test_quit_confirmation_can_cancel_and_does_not_stack_on_repeated_ctrl_q():
    app = SessionApp()
    async with app.run_test() as pilot:
        session = SshSession("live")
        await app.query_one(SessionTabs).add_session(session)
        await pilot.press("ctrl+q")
        assert isinstance(app.screen, ConfirmCloseScreen)
        depth = len(app.screen_stack)
        await pilot.press("ctrl+q")
        assert len(app.screen_stack) == depth
        await pilot.click("#close-cancel")
        assert not session._disposed
        await pilot.press("ctrl+q")
        await pilot.click("#close-confirm")
    assert session._disposed


async def test_quit_with_only_exited_sessions_needs_no_confirmation():
    app = SessionApp()
    async with app.run_test() as pilot:
        session = SshSession("exited")
        await app.query_one(SessionTabs).add_session(session)
        session._set_state(SessionState.DISCONNECTED)
        await pilot.press("ctrl+q")
        assert not isinstance(app.screen, ConfirmCloseScreen)
    assert session._disposed
