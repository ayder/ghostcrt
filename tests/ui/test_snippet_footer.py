import asyncio
from pathlib import Path

from textual.app import App
from textual.widgets import Input, Static, Tree

from ghostcrt.config.inventory import HostInventory
from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostList
from ghostcrt.ui.widgets.session_tabs import SessionTabs
from ghostcrt.ui.widgets.snippet_bar import SnippetBar, SnippetButton
from ghostcrt.vault.vault import Vault

DEFINED = [(1, "sudo", "synthetic-pw\\n"), (3, "logs", "tail -f x\\n")]


def snippet_app(tmp_path, snippets=DEFINED):
    includes = tmp_path / "includes"
    includes.mkdir()
    (includes / "production.conf").write_text("Host web01\n")
    config = tmp_path / "config"
    config.write_text(f"Include {includes}/*\n")
    vault = Vault.create(tmp_path / "vault.enc", "synthetic-master")
    for slot, name, text in snippets:
        vault.update_snippet(slot, name, text)

    class SnippetApp(App[None]):
        CSS_PATH = str(Path(__file__).parents[2] / "src/ghostcrt/ui/compact.tcss")

        def on_mount(self):
            self.main_screen = MainScreen(vault, HostInventory(config, includes))
            self.push_screen(self.main_screen)

    return SnippetApp(), vault


async def settle(pilot) -> None:
    for _ in range(3):
        await pilot.pause()
    await asyncio.sleep(0.01)


async def open_session(pilot, *, state=SessionState.CONNECTED):
    screen = pilot.app.main_screen
    session = SshSession("web01")
    session.state = state
    sent: list[bytes] = []

    async def record(data: bytes) -> None:
        sent.append(data)

    session.send = record  # type: ignore[method-assign]
    tabs = screen.query_one(SessionTabs)
    pane_id = await tabs.add_session(session)
    await settle(pilot)
    return tabs, pane_id, sent


def hint(screen) -> str:
    return str(screen.query_one("#context-status", Static).content)


def visible_labels(screen) -> list[str]:
    bar = screen.query_one(SnippetBar)
    return [str(b.label) for b in bar.query(SnippetButton) if b.display]


def record_notifications(screen) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake_notify(message, *, title="", severity="information", timeout=None, markup=True):
        calls.append((message, severity))

    screen.notify = fake_notify
    return calls


async def test_bar_shows_defined_snippets_only_while_terminal_focused(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        bar = screen.query_one(SnippetBar)
        assert not bar.display  # Hosts focused at start

        tabs, _pane, _sent = await open_session(pilot)
        assert tabs.active_terminal.has_focus
        assert bar.display
        assert visible_labels(screen) == ["1 sudo", "3 logs"]
        assert "Ctrl+N Snippet" in hint(screen)

        await pilot.press("ctrl+t")
        await settle(pilot)
        assert screen.query_one(Tree).has_focus
        assert not bar.display


async def test_snippet_names_are_shown_literally(tmp_path):
    app, _vault = snippet_app(tmp_path, snippets=[(2, "[b]x", "y")])
    async with app.run_test(size=(120, 30)) as pilot:
        await open_session(pilot)

        assert visible_labels(app.main_screen) == ["2 [b]x"]


async def test_ctrl_n_then_digit_types_that_snippet(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        _tabs, _pane, sent = await open_session(pilot)

        await pilot.press("ctrl+n")
        await settle(pilot)
        assert "SNIPPET  1–5 Send · Esc Cancel" in hint(screen)

        await pilot.press("3")
        await settle(pilot)
        assert b"".join(sent) == b"tail -f x\r"
        assert "TERMINAL" in hint(screen)


async def test_ctrl_n_then_empty_slot_warns_and_sends_nothing(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        notes = record_notifications(screen)
        _tabs, _pane, sent = await open_session(pilot)

        await pilot.press("ctrl+n", "2")
        await settle(pilot)

        assert sent == []
        assert ("Snippet 2 is empty.", "warning") in notes


async def test_ctrl_n_then_other_key_cancels_and_drops_it(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        _tabs, _pane, sent = await open_session(pilot)

        await pilot.press("ctrl+n", "x")
        await settle(pilot)
        assert sent == []
        assert "TERMINAL" in hint(screen)

        await pilot.press("x")
        await settle(pilot)
        assert b"".join(sent) == b"x"


async def test_disconnected_session_warns_and_sends_nothing(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        notes = record_notifications(screen)
        _tabs, _pane, sent = await open_session(pilot, state=SessionState.DISCONNECTED)

        await pilot.press("ctrl+n", "1")
        await settle(pilot)

        assert sent == []
        assert ("Session is not connected.", "warning") in notes


async def test_ctrl_n_outside_terminal_still_focuses_hosts(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        await open_session(pilot)
        screen.action_focus_search()
        await settle(pilot)
        assert screen.query_one(HostList).query_one(Input).has_focus

        await pilot.press("ctrl+n")
        await settle(pilot)

        assert screen.query_one(Tree).has_focus


async def test_clicking_a_snippet_button_types_it_and_keeps_terminal_focus(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        tabs, _pane, sent = await open_session(pilot)

        await pilot.click("#snippet-1")
        await settle(pilot)

        assert b"".join(sent) == b"synthetic-pw\r"
        assert tabs.active_terminal.has_focus


async def test_closing_the_session_while_armed_clears_snippet_hint(tmp_path):
    app, _vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        tabs, pane_id, _sent = await open_session(pilot)
        await pilot.press("ctrl+n")
        await settle(pilot)

        await tabs.close_session(pane_id)
        await settle(pilot)

        assert "SNIPPET" not in hint(screen)
        assert not screen.query_one(SnippetBar).display


async def test_refresh_snippets_updates_the_bar(tmp_path):
    app, vault = snippet_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        screen = app.main_screen
        await open_session(pilot)

        vault.update_snippet(5, "psql", "psql\\n")
        vault.update_snippet(1, "sudo", None)
        screen.refresh_snippets()
        await settle(pilot)

        assert visible_labels(screen) == ["3 logs", "5 psql"]
