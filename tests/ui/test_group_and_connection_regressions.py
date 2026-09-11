import os

import pytest
from textual.app import App
from textual.widgets import Input, TextArea, Tree

from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigStore
from ghostcrt.models import Host
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.host_edit import HostEditModal, HostEditResult
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostList


class FakeVault:
    def __init__(self, password=None):
        self.password = password

    def get(self, alias):
        return self.password

    def profiles(self):
        return []

    def profile_for(self, alias):
        return None

    def update_assignment(self, alias, profile_id):
        return None


def make_app(tmp_path, *, config=None, password=None):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text(f"Include {inc}/*.conf\nHost duplicate\n User readonly\n")
    (inc / "aaa.conf").write_text("Host duplicate\n User first\n")
    (inc / "bbb.conf").write_text("Host duplicate\n User second\n")
    (inc / "destination.conf").write_text("")
    inventory = HostInventory(cfg, inc)

    class TestApp(App):
        def on_mount(self):
            self.push_screen(MainScreen(FakeVault(password), inventory, ssh_config=config))

    return TestApp(), inventory


async def highlight(pilot, group):
    tree = pilot.app.screen.query_one(HostList).query_one(Tree)
    node = next(n for n in tree.root.children if n.data.group == group)
    tree.move_cursor(node.children[0])
    await pilot.pause()
    assert pilot.app.screen.query_one(HostList).selected_group == group


@pytest.mark.parametrize("action", ["edit", "delete"])
async def test_readonly_duplicate_cannot_modify_writable_copy(tmp_path, action):
    app, _ = make_app(tmp_path)
    async with app.run_test() as pilot:
        await highlight(pilot, READONLY_GROUP)
        screen = app.screen
        getattr(screen, f"_host_{action}")()
        await pilot.pause()
        assert app.screen is screen
        assert SshConfigStore(tmp_path / "includes/aaa.conf").get("duplicate").user == "first"


@pytest.mark.parametrize("action", ["edit", "delete", "move"])
async def test_actions_target_selected_writable_duplicate(tmp_path, monkeypatch, action):
    app, _ = make_app(tmp_path)
    async with app.run_test() as pilot:
        await highlight(pilot, "bbb")
        screen = app.screen
        if action == "delete":
            screen._host_delete()
        elif action == "edit":
            screen._host_edit()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="duplicate", user="edited"), None))
        else:
            monkeypatch.setattr(screen, "_pick_group", lambda then: then("destination"))
            screen._host_copy_to_group()
        await pilot.pause()
        assert SshConfigStore(tmp_path / "includes/aaa.conf").get("duplicate").user == "first"
        second = SshConfigStore(tmp_path / "includes/bbb.conf").get("duplicate")
        if action == "edit":
            assert second.user == "edited"
        else:
            assert second is None
        if action == "move":
            assert (
                SshConfigStore(tmp_path / "includes/destination.conf").get("duplicate").user
                == "second"
            )


async def test_copy_from_readonly_duplicate_adopts_selected_stanza(tmp_path, monkeypatch):
    app, _ = make_app(tmp_path)
    async with app.run_test() as pilot:
        await highlight(pilot, READONLY_GROUP)
        monkeypatch.setattr(app.screen, "_pick_group", lambda then: then("destination"))
        app.screen._host_copy_to_group()
        await pilot.pause()
        assert (
            SshConfigStore(tmp_path / "includes/destination.conf").get("duplicate").user
            == "readonly"
        )
        assert SshConfigStore(tmp_path / "includes/aaa.conf").get("duplicate").user == "first"
        assert SshConfigStore(tmp_path / "config").get("duplicate").user == "readonly"


async def test_filter_clears_hidden_selection(tmp_path):
    app, _ = make_app(tmp_path)
    async with app.run_test() as pilot:
        await highlight(pilot, "bbb")
        host_list = app.screen.query_one(HostList)
        host_list.query_one("#host-filter", Input).value = "not-found"
        await pilot.pause()
        assert host_list.selected_host is None
        assert host_list.selected_group is None


async def test_identity_editor_preserves_and_edits_multiple_files():
    class TestApp(App):
        def on_mount(self):
            self.push_screen(HostEditModal(Host(alias="sample", identity_file=["one", "two"])))

    app = TestApp()
    async with app.run_test(size=(120, 40)):
        field = app.screen.query_one("#identity", TextArea)
        assert field.text == "one\ntwo"
        assert app.screen._build_host().identity_file == ["one", "two"]
        field.text = "two\nthree"
        assert app.screen._build_host().identity_file == ["two", "three"]


@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("password", [None, "synthetic-password"])
async def test_connection_and_reconnect_use_selected_config(
    tmp_path, monkeypatch, custom, password
):
    config = tmp_path / "config" if custom else None
    app, _ = make_app(tmp_path, config=config, password=password)
    calls = []

    async def capture(self, argv, **kwargs):
        calls.append(argv)
        for name in ("read_fd", "write_fd"):
            if kwargs.get(name) is not None:
                os.close(kwargs[name])

    monkeypatch.setattr(SshSession, "start", capture)
    monkeypatch.setattr(SshSession, "reconnect", capture)
    monkeypatch.setattr("ghostcrt.ui.screens.main.shutil.which", lambda name: "/synthetic/sshpass")
    async with app.run_test() as pilot:
        screen = app.screen
        await screen.open_session(Host(alias="duplicate")).wait()
        await pilot.pause()
        await screen._reconnect().wait()
        assert len(calls) == 2
        for argv in calls:
            ssh = argv[argv.index("ssh") :]
            expected = ["ssh", "-tt"]
            if custom:
                expected += ["-F", str(config)]
            assert ssh == [*expected, "--", "duplicate"]
