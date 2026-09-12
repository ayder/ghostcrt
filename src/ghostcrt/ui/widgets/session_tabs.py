from __future__ import annotations

import asyncio

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import TabbedContent, TabPane

from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.confirm_close import ConfirmCloseScreen
from ghostcrt.ui.widgets.session_tab import SessionTab, SessionTabbedContent
from ghostcrt.ui.widgets.terminal import TerminalWidget
from ghostcrt.ui.widgets.terminal_pane import TerminalPane


def tab_title(alias: str, state: SessionState, exit_code: int | None) -> str:
    if state == SessionState.DISCONNECTED:
        code = exit_code if exit_code is not None else "?"
        return f"{alias} [exit {code}]"
    return alias


class SessionTabs(Container):
    DEFAULT_CSS = """
    SessionTabs {
        height: 1fr;
        width: 1fr;
    }
    SessionTabs TabbedContent {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: dict[str, SshSession] = {}
        self._counter = 0
        self._close_lock = asyncio.Lock()
        self._sessions_closing = False
        self._close_prompt_pending = False

    def compose(self) -> ComposeResult:
        yield SessionTabbedContent(id="session-tabs")

    @property
    def has_live_sessions(self) -> bool:
        return any(s.state != SessionState.DISCONNECTED for s in self._sessions.values())

    @property
    def active_session(self) -> SshSession | None:
        tabs = self.query_one("#session-tabs", TabbedContent)
        active = tabs.active
        if not active:
            return None
        return self._sessions.get(str(active))

    @property
    def active_terminal(self) -> TerminalWidget | None:
        tabs = self.query_one("#session-tabs", TabbedContent)
        active = tabs.active
        if not active:
            return None
        try:
            return tabs.query_one(f"#{active}", TabPane).query_one(TerminalWidget)
        except Exception:
            return None

    async def add_session(self, session: SshSession) -> str:
        async with self._close_lock:
            if self._sessions_closing:
                raise RuntimeError("session tabs are closing")
            self._counter += 1
            pane_id = f"sess-{self._counter}"
            self._sessions[pane_id] = session
            title = tab_title(session.alias, session.state, session.exit_code)
            tabs = self.query_one("#session-tabs", SessionTabbedContent)
            terminal = TerminalWidget(session, id=f"term-{pane_id}")
            pane = TabPane(title, TerminalPane(terminal), id=pane_id)

            def on_state(state: SessionState) -> None:
                try:
                    tab = tabs.get_tab(pane_id)
                    if isinstance(tab, SessionTab):
                        tab.set_title(tab_title(session.alias, state, session.exit_code))
                except Exception:
                    pass

            session.on_state = on_state
            try:
                await tabs.add_session_pane(pane, title)
            except BaseException:
                self._sessions.pop(pane_id, None)
                if session.on_state == on_state:
                    session.on_state = None
                session.on_output = None
                raise
            tabs.active = pane_id
            tab = tabs.get_tab(pane_id)
            assert isinstance(tab, SessionTab)
            tab.set_title(tab_title(session.alias, session.state, session.exit_code))

            # Await one completed layout pass. Mounting a pane is awaitable,
            # but its reactive activation may not have assigned geometry yet.
            # Starting SSH before this point can still produce a transient 1x1
            # PTY even though the pane reaches its final size moments later.
            layout_ready = asyncio.get_running_loop().create_future()

            def after_layout() -> None:
                terminal.sync_pty_size()
                terminal.focus()
                if not layout_ready.done():
                    layout_ready.set_result(None)

            if self.call_after_refresh(after_layout):
                await layout_ready
            else:
                after_layout()
            return pane_id

    @on(SessionTab.CloseRequested)
    def on_tab_close_requested(self, message: SessionTab.CloseRequested) -> None:
        message.stop()
        self.request_close(message.pane_id)

    def request_close_active(self) -> None:
        active = self.query_one("#session-tabs", TabbedContent).active
        if active:
            self.request_close(str(active))

    def request_close(self, pane_id: str) -> None:
        session = self._sessions.get(pane_id)
        if session is None or self._sessions_closing or self._close_prompt_pending:
            return
        if session.state == SessionState.DISCONNECTED:
            self.run_worker(self.close_session(pane_id))
            return
        self._close_prompt_pending = True

        def confirmed(close: bool) -> None:
            self._close_prompt_pending = False
            if close:
                self.run_worker(self.close_session(pane_id))

        self.app.push_screen(
            ConfirmCloseScreen(
                f"Session {session.alias} is still running or connecting. "
                "Closing it will disconnect SSH. Close this session?"
            ),
            confirmed,
        )

    async def close_active(self) -> None:
        tabs = self.query_one("#session-tabs", TabbedContent)
        active = tabs.active
        if active:
            await self.close_session(str(active))

    async def close_session(self, pane_id: str) -> None:
        """Close a specific session, tolerating concurrent removal."""
        async with self._close_lock:
            session = self._sessions.pop(pane_id, None)
            if session is None:
                return
            session.on_state = None
            tabs = self.query_one("#session-tabs", TabbedContent)
            await tabs.remove_pane(pane_id)
            await session.close()

    async def close_all(self) -> None:
        async with self._close_lock:
            self._sessions_closing = True
            sessions = list(self._sessions.values())
            self._sessions.clear()
            for session in sessions:
                session.on_state = None
                session.on_output = None
            await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)

    async def on_unmount(self) -> None:
        # Also covers crashes, app.exit(), and quitting while a modal is active.
        await self.close_all()
