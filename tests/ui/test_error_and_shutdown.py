import asyncio
import sys

import pytest
from textual.app import App
from textual.widgets import Input

from ghostcrt.app import GhostCRTApp
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.help import HelpScreen
from ghostcrt.ui.screens.unlock import UnlockScreen
from ghostcrt.ui.widgets.session_tabs import SessionTabs


@pytest.mark.parametrize("rich_error", [False, True])
def test_crash_output_omits_passwords_keys_and_exception_renderers(
    tmp_home, monkeypatch, capsys, rich_error
):
    class SensitiveError(RuntimeError):
        def __rich__(self):
            return "synthetic-rich-secret"

    def fail():
        master_password = "synthetic-master-secret"
        ssh_password = "synthetic-ssh-secret"
        key = b"synthetic-key-secret"
        error_type = SensitiveError if rich_error else RuntimeError
        raise error_type(f"{master_password} {ssh_password} {key!r}")

    monkeypatch.setattr(GhostCRTApp, "on_mount", lambda self: self.call_after_refresh(fail))
    app = GhostCRTApp()
    app.run(headless=True)
    output = capsys.readouterr()
    rendered = output.out + output.err
    assert app.return_code == 1
    assert "unexpected error" in rendered
    for secret in (
        "synthetic-master-secret",
        "synthetic-ssh-secret",
        "synthetic-key-secret",
        "synthetic-rich-secret",
    ):
        assert secret not in rendered


async def test_vault_creation_io_error_stays_in_ui(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("synthetic-private-detail")

    monkeypatch.setattr("ghostcrt.vault.vault._atomic_write", fail)

    class TestApp(App):
        def on_mount(self):
            self.push_screen(UnlockScreen(tmp_path / "vault.enc"))

    app = TestApp()
    async with app.run_test() as pilot:
        app.screen.query_one("#password", Input).value = "synthetic-master-secret"
        app.screen.query_one("#confirm", Input).value = "synthetic-master-secret"
        await pilot.click("#submit")
        assert "Unable to create vault" in str(app.screen.query_one("#unlock-error").render())
        assert app._exception is None


@pytest.mark.parametrize("mode", ["quit", "exit", "crash"])
async def test_modal_shutdown_closes_and_reaps_sessions(mode):
    class TestApp(App):
        action_quit = GhostCRTApp.action_quit
        _handle_exception = GhostCRTApp._handle_exception

        def compose(self):
            yield SessionTabs()

    app = TestApp()
    session = SshSession("local-review-process")
    proc = None
    try:
        async with app.run_test() as pilot:
            await app.query_one(SessionTabs).add_session(session)
            await session.start([sys.executable, "-c", "import time; time.sleep(60)"])
            proc = session._proc
            await app.push_screen(HelpScreen())
            await pilot.pause()
            if mode == "quit":
                await app.action_quit()
            elif mode == "exit":
                app.exit()
            else:
                # Simulate Textual's exception shutdown while retaining the
                # original exception for the test runner to propagate.
                app._handle_exception(RuntimeError("synthetic failure"))
                app._exception = None
        assert session._disposed
        assert session._proc is None
        assert proc._closed
        assert proc._exit_code is not None
    finally:
        await asyncio.wait_for(session.close(), timeout=5)
