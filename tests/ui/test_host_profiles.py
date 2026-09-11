from __future__ import annotations

import os

import pytest
from textual.app import App
from textual.widgets import Select, Tree
from textual.widgets._select import SelectOverlay

from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigStore
from ghostcrt.models import Host
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.host_edit import HostEditModal, HostEditResult
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.screens.profile_picker import ProfilePick
from ghostcrt.ui.widgets.host_list import HostList
from ghostcrt.vault.vault import Vault, VaultError, VaultInputError


def make_vault_app(tmp_path, *, block="Host duplicate\n User second\n"):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text(f"Include {inc}/*.conf\nHost duplicate\n User readonly\n")
    (inc / "aaa.conf").write_text("Host duplicate\n User first\n")
    (inc / "bbb.conf").write_text(block)
    (inc / "destination.conf").write_text("")
    inventory = HostInventory(cfg, inc)
    vault = Vault.create(tmp_path / "vault.enc", "synthetic-master")

    class TestApp(App):
        def on_mount(self):
            self.push_screen(MainScreen(vault, inventory))

    return TestApp(), inventory, vault


async def highlight_alias(pilot, group, alias):
    tree = pilot.app.screen.query_one(HostList).query_one(Tree)
    group_node = next(n for n in tree.root.children if n.data.group == group)
    node = next(
        c for c in group_node.children if c.data.host is not None and c.data.host.alias == alias
    )
    tree.move_cursor(node)
    await pilot.pause()
    host_list = pilot.app.screen.query_one(HostList)
    assert host_list.selected_host.alias == alias
    assert host_list.selected_group == group


def _record_notifications(screen):
    calls = []

    def fake_notify(message, *, title="", severity="information", timeout=None, markup=True):
        calls.append((message, severity))

    screen.notify = fake_notify
    return calls


def _select_prompts(select):
    overlay = select.query_one(SelectOverlay)
    return [str(overlay.get_option_at_index(i).prompt) for i in range(overlay.option_count)]


class TestMainScreenProfiles:
    async def test_edit_writes_to_selected_alias_of_multi_alias_block(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path, block="Host srv1 srv2 srv3\n User u\n")
        vault.update_profile("ops", "s3")

        async with app.run_test() as pilot:
            await highlight_alias(pilot, "bbb", "srv2")
            app.screen._host_edit()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(
                HostEditResult(
                    Host(alias="srv1", aliases=["srv1", "srv2", "srv3"], user="edited"),
                    "ops",
                )
            )
            await pilot.pause()

        assert vault.profile_for("srv2") == "ops"
        assert vault.profile_for("srv1") is None
        assert vault.profile_for("srv3") is None

        # Independent read: a separate Vault instance re-reads the file from disk.
        reread = Vault.unlock(vault.path, "synthetic-master")
        assert reread.aliases() == ["srv2"]
        assert reread.profile_for("srv2") == "ops"

    async def test_renaming_selected_alias_moves_assignment_to_first_alias(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path, block="Host srv1 srv2 srv3\n User u\n")
        vault.update_profile("ops", "s3")
        vault.update_assignment("srv2", "ops")
        vault.update_assignment("srv3", "ops")

        async with app.run_test() as pilot:
            await highlight_alias(pilot, "bbb", "srv2")
            app.screen._host_edit()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(
                HostEditResult(
                    Host(alias="srv1", aliases=["srv1", "srvX", "srv3"]),
                    "ops",
                )
            )
            await pilot.pause()

        assert vault.profile_for("srv2") is None
        assert vault.profile_for("srv1") == "ops"
        assert vault.profile_for("srv3") == "ops"

    async def test_editor_opens_with_selected_alias_profile(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path, block="Host srv1 srv2 srv3\n User u\n")
        vault.update_profile("ops", "s3")
        vault.update_profile("db", "d")
        vault.update_assignment("srv1", "ops")
        vault.update_assignment("srv2", "db")

        async with app.run_test() as pilot:
            await highlight_alias(pilot, "bbb", "srv2")
            app.screen._host_edit()
            await pilot.pause()

            assert isinstance(app.screen, HostEditModal)
            select = app.screen.query_one("#vault-profile", Select)
            assert select.value == "db"
            assert _select_prompts(select) == ["(none)", "db", "ops"]

    async def test_add_writes_assignment_only_when_chosen(self, tmp_path, monkeypatch):
        app, _inventory, vault = make_vault_app(tmp_path)
        vault.update_profile("ops", "s3")

        async with app.run_test() as pilot:
            screen = app.screen
            monkeypatch.setattr(screen, "_pick_group", lambda then: then("destination"))

            screen._host_add()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="newhost"), "ops"))
            await pilot.pause()
            assert vault.profile_for("newhost") == "ops"

            aliases_before = vault.aliases()
            bytes_before = vault.path.read_bytes()

            screen._host_add()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="plain"), None))
            await pilot.pause()

            assert vault.aliases() == aliases_before
            assert vault.path.read_bytes() == bytes_before

    async def test_assignment_failure_is_reported_and_host_stays_written(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path)
        vault.update_profile("ops", "s3")

        def fail(alias, profile_id):
            raise VaultError("simulated")

        async with app.run_test() as pilot:
            screen = app.screen
            vault.update_assignment = fail
            notifications = _record_notifications(screen)

            await highlight_alias(pilot, "bbb", "duplicate")
            screen._host_edit()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="duplicate", user="edited"), "ops"))
            await pilot.pause()

        assert (
            SshConfigStore(tmp_path / "includes" / "bbb.conf").get("duplicate").user == "edited"
        )
        assert notifications == [
            (
                (
                    "Host saved; profile assignment was not. "
                    "Use Vault → Assign profile to selected host… to retry."
                ),
                "error",
            )
        ]


class TestVaultMenu:
    async def test_create_assign_delete_round_trip_with_notifications(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path)

        async with app.run_test() as pilot:
            screen = app.screen
            notifications = _record_notifications(screen)
            await highlight_alias(pilot, "bbb", "duplicate")

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("profile")
            await pilot.pause()
            app.screen.dismiss(("ops", "s3"))
            await pilot.pause()

            assert vault.get_profile("ops") == "s3"
            assert ("Saved profile ops", "information") in notifications

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("assign")
            await pilot.pause()
            app.screen.dismiss(ProfilePick("ops"))
            await pilot.pause()

            assert vault.get("duplicate") == "s3"
            assert ("Assigned ops to duplicate", "information") in notifications

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("delete-profile")
            await pilot.pause()
            app.screen.dismiss(ProfilePick("ops"))
            await pilot.pause()

            assert vault.profiles() == []
            assert vault.get("duplicate") is None
            assert ("Deleted profile ops", "information") in notifications

        reread = Vault.unlock(vault.path, "synthetic-master")
        assert reread.aliases() == []

    async def test_assign_none_removes_assignment(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path)
        vault.update_profile("ops", "s3")
        vault.update_assignment("duplicate", "ops")

        async with app.run_test() as pilot:
            screen = app.screen
            notifications = _record_notifications(screen)
            await highlight_alias(pilot, "bbb", "duplicate")

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("assign")
            await pilot.pause()
            app.screen.dismiss(ProfilePick(None))
            await pilot.pause()

        assert vault.profile_for("duplicate") is None
        assert vault.get_profile("ops") == "s3"
        assert ("Removed profile from duplicate", "information") in notifications

    async def test_assign_on_readonly_host_leaves_config_untouched(self, tmp_path):
        app, _inventory, vault = make_vault_app(tmp_path)
        vault.update_profile("ops", "s3")

        async with app.run_test() as pilot:
            screen = app.screen
            _record_notifications(screen)
            await highlight_alias(pilot, READONLY_GROUP, "duplicate")

            before = (tmp_path / "config").read_bytes()

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("assign")
            await pilot.pause()
            app.screen.dismiss(ProfilePick("ops"))
            await pilot.pause()

        assert vault.profile_for("duplicate") == "ops"
        assert (tmp_path / "config").read_bytes() == before

    async def test_empty_vault_guards(self, tmp_path):
        app, _inventory, _vault = make_vault_app(tmp_path)

        async with app.run_test() as pilot:
            screen = app.screen
            notifications = _record_notifications(screen)
            await highlight_alias(pilot, "bbb", "duplicate")

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("delete-profile")
            await pilot.pause()

            assert ("No profiles yet. Create one first.", "warning") in notifications
            assert app.screen is screen

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("assign")
            await pilot.pause()

            assert notifications.count(("No profiles yet. Create one first.", "warning")) == 2
            assert app.screen is screen

    @pytest.mark.parametrize("state", ["ops", "empty"])
    async def test_assign_without_selection_warns(self, tmp_path, state):
        app, _inventory, vault = make_vault_app(tmp_path)
        if state == "ops":
            vault.update_profile("ops", "s3")

        async with app.run_test() as pilot:
            screen = app.screen
            notifications = _record_notifications(screen)
            assert screen.query_one(HostList).selected_host is None

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("assign")
            await pilot.pause()

            assert ("Select a host first.", "warning") in notifications
            assert not any(
                msg == "No profiles yet. Create one first." for msg, _ in notifications
            )
            assert app.screen is screen

    @pytest.mark.parametrize("case", ["disk", "input"])
    async def test_save_failure_is_reported_by_message(self, tmp_path, monkeypatch, case):
        app, _inventory, vault = make_vault_app(tmp_path)

        async with app.run_test() as pilot:
            screen = app.screen
            notifications = _record_notifications(screen)

            if case == "disk":

                def boom_replace(*args, **kwargs):
                    raise OSError("disk full")

                monkeypatch.setattr("ghostcrt.vault.vault.os.replace", boom_replace)
            else:

                def boom_update(profile_id, password):
                    raise VaultInputError("Unknown profile.")

                vault.update_profile = boom_update

            screen.on_vault_menu()
            await pilot.pause()
            app.screen.dismiss("profile")
            await pilot.pause()
            app.screen.dismiss(("ops", "s3"))
            await pilot.pause()

        if case == "disk":
            assert (
                "Unable to save vault. Check disk space and permissions.",
                "error",
            ) in notifications
            assert vault.profiles() == []
        else:
            assert ("Unknown profile.", "error") in notifications


class TestConnectPath:
    @pytest.mark.parametrize("assigned", [True, False])
    async def test_connect_uses_resolved_profile_password(self, tmp_path, monkeypatch, assigned):
        app, _inventory, vault = make_vault_app(tmp_path)
        if assigned:
            vault.update_profile("ops", "s3")
            vault.update_assignment("duplicate", "ops")

        calls = []

        async def capture(self, argv, **kwargs):
            calls.append(argv)
            for name in ("read_fd", "write_fd"):
                if kwargs.get(name) is not None:
                    os.close(kwargs[name])

        monkeypatch.setattr(SshSession, "start", capture)
        monkeypatch.setattr(
            "ghostcrt.ui.screens.main.shutil.which", lambda name: "/synthetic/sshpass"
        )

        async with app.run_test() as pilot:
            screen = app.screen
            await screen.open_session(Host(alias="duplicate")).wait()
            await pilot.pause()

        assert len(calls) == 1
        argv = calls[0]
        if assigned:
            assert argv[:2] == ["sshpass", "-d"]
        else:
            assert argv[0] == "ssh"
