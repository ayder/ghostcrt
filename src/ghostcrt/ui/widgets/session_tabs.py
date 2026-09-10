from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import TabbedContent, TabPane

from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.widgets.terminal import TerminalWidget


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

    def compose(self) -> ComposeResult:
        yield TabbedContent(id="session-tabs")

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
            tabs = self.query_one("#session-tabs", TabbedContent)
            terminal = TerminalWidget(session, id=f"term-{pane_id}")
            pane = TabPane(title, terminal, id=pane_id)

            def on_state(state: SessionState) -> None:
                try:
                    tab = tabs.get_tab(pane_id)
                    tab.label = tab_title(session.alias, state, session.exit_code)
                except Exception:
                    pass

            session.on_state = on_state
            try:
                await tabs.add_pane(pane)
            except BaseException:
                self._sessions.pop(pane_id, None)
                if session.on_state == on_state:
                    session.on_state = None
                session.on_output = None
                raise
            tabs.active = pane_id
            tabs.get_tab(pane_id).label = tab_title(session.alias, session.state, session.exit_code)

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
