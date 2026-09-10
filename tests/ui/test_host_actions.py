from pathlib import Path

import pytest
from textual.app import App

from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigError
from ghostcrt.models import Host
from ghostcrt.ui.screens.main import MainScreen


class FakeVault:
    def get(self, alias):
        return None


def inventory(tmp_path: Path) -> HostInventory:
    inc = tmp_path / "includes"
    inc.mkdir()
    (inc / "production.conf").write_text("Host srv1\n    User jorn\n")
    cfg = tmp_path / "config"
    cfg.write_text(f"Include {inc}/*\n\nHost bastion\n    User bob\n")
    return HostInventory(cfg, inc)


def screen_app(inv: HostInventory) -> App[None]:
    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(MainScreen(FakeVault(), inv))

    return TestApp()


async def test_readonly_hosts_are_identified(tmp_path):
    inv = inventory(tmp_path)
    app = screen_app(inv)
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.screen._is_read_only(READONLY_GROUP) is True
        assert app.screen._is_read_only("production") is False


async def test_writable_groups_excludes_ssh_config(tmp_path):
    inv = inventory(tmp_path)
    app = screen_app(inv)
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.screen._writable_groups() == ["production"]


def test_deleting_a_readonly_host_raises(tmp_path):
    inv = inventory(tmp_path)

    with pytest.raises(SshConfigError, match="read-only"):
        inv.delete(READONLY_GROUP, "bastion")


def test_adopt_makes_a_readonly_host_editable(tmp_path):
    inv = inventory(tmp_path)

    inv.adopt("bastion", "production")

    assert inv.group_of("bastion") == "production"
    inv.update("production", "bastion", Host(alias="bastion", user="alice"))

    assert "alice" in (tmp_path / "includes" / "production.conf").read_text()
    # The original stays put and is simply shadowed.
    assert "User bob" in (tmp_path / "config").read_text()


async def test_group_picker_returns_an_existing_group(tmp_path):
    from ghostcrt.ui.screens.group_picker import GroupPickerScreen

    chosen: list[str | None] = []

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(GroupPickerScreen(["production", "staging"]), chosen.append)

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        options = app.screen.query_one("#group-options")
        options.highlighted = 1
        options.action_select()
        await pilot.pause()

    assert chosen == ["staging"]


async def test_group_picker_returns_a_new_name(tmp_path):
    from ghostcrt.ui.screens.group_picker import GroupPickerScreen

    chosen: list[str | None] = []

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(GroupPickerScreen(["production"]), chosen.append)

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#new-group").value = "brand-new"
        await pilot.click("#create")
        await pilot.pause()

    assert chosen == ["brand-new"]
