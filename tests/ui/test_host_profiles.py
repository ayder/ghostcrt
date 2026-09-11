from __future__ import annotations

from textual.app import App
from textual.widgets import Select, Tree
from textual.widgets._select import SelectOverlay

from ghostcrt.config.inventory import HostInventory
from ghostcrt.config.ssh_config import SshConfigStore
from ghostcrt.models import Host
from ghostcrt.ui.screens.host_edit import HostEditModal, HostEditResult
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostList
from ghostcrt.vault.vault import Vault, VaultError


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
