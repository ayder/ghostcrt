from pathlib import Path

from textual.app import App
from textual.widgets import Tree

from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigStore
from ghostcrt.models import Host
from ghostcrt.ui.screens.group_picker import GroupPickerScreen
from ghostcrt.ui.screens.host_edit import HostEditModal, HostEditResult
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostList


class FakeVault:
    def get(self, alias):
        return None

    def profiles(self):
        return []

    def profile_for(self, alias):
        return None

    def update_assignment(self, alias, profile_id):
        return None


def inventory(tmp_path: Path) -> HostInventory:
    inc = tmp_path / "includes"
    inc.mkdir()
    (inc / "production.conf").write_text("Host srv1\n    User jorn\n")
    (inc / "staging.conf").write_text("")
    cfg = tmp_path / "config"
    cfg.write_text(f"Include {inc}/*\n\nHost bastion\n    User bob\n")
    return HostInventory(cfg, inc)


def screen_app(inv: HostInventory) -> App[None]:
    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(MainScreen(FakeVault(), inv))

    return TestApp()


def _record_notifications(screen):
    calls = []

    def fake_notify(message, *, title="", severity="information", timeout=None, markup=True):
        calls.append((message, severity))

    screen.notify = fake_notify
    return calls


async def highlight(pilot, group):
    tree = pilot.app.screen.query_one(HostList).query_one(Tree)
    node = next(n for n in tree.root.children if n.data.group == group)
    tree.move_cursor(node.children[0])
    await pilot.pause()
    assert pilot.app.screen.query_one(HostList).selected_group == group


class TestPickGroup:
    async def test_cancelled_add_notifies_and_writes_nothing(self, tmp_path):
        inv = inventory(tmp_path)
        app = screen_app(inv)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            notifications = _record_notifications(screen)

            includes_dir = tmp_path / "includes"
            before_listing = sorted(p.name for p in includes_dir.iterdir())
            before_bytes = (includes_dir / "production.conf").read_bytes()

            screen._host_add()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="newhost"), None))
            await pilot.pause()
            assert isinstance(app.screen, GroupPickerScreen)
            await pilot.click("#cancel")
            await pilot.pause()

            assert ("Host not saved: no group chosen.", "warning") in notifications
            assert (includes_dir / "production.conf").read_bytes() == before_bytes
            assert sorted(p.name for p in includes_dir.iterdir()) == before_listing

    async def test_cancelled_copy_notifies(self, tmp_path):
        inv = inventory(tmp_path)
        app = screen_app(inv)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            notifications = _record_notifications(screen)

            includes_dir = tmp_path / "includes"
            before_bytes = (includes_dir / "production.conf").read_bytes()

            await highlight(pilot, READONLY_GROUP)

            screen._host_copy_to_group()
            await pilot.pause()
            assert isinstance(app.screen, GroupPickerScreen)
            await pilot.click("#cancel")
            await pilot.pause()

            assert ("Host not saved: no group chosen.", "warning") in notifications
            assert (includes_dir / "production.conf").read_bytes() == before_bytes

    async def test_escape_cancels_add_with_warning(self, tmp_path):
        inv = inventory(tmp_path)
        app = screen_app(inv)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            notifications = _record_notifications(screen)

            includes_dir = tmp_path / "includes"
            before_bytes = (includes_dir / "production.conf").read_bytes()

            screen._host_add()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="newhost"), None))
            await pilot.pause()
            assert isinstance(app.screen, GroupPickerScreen)
            await pilot.press("escape")
            await pilot.pause()

            assert ("Host not saved: no group chosen.", "warning") in notifications
            assert (includes_dir / "production.conf").read_bytes() == before_bytes

    async def test_typed_new_group_is_created(self, tmp_path):
        inv = inventory(tmp_path)
        app = screen_app(inv)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            notifications = _record_notifications(screen)

            includes_dir = tmp_path / "includes"
            assert not (includes_dir / "brand-new.conf").exists()

            screen._host_add()
            await pilot.pause()
            assert isinstance(app.screen, HostEditModal)
            app.screen.dismiss(HostEditResult(Host(alias="h1"), None))
            await pilot.pause()
            assert isinstance(app.screen, GroupPickerScreen)
            app.screen.query_one("#new-group").value = "brand-new"
            await pilot.click("#create")
            await pilot.pause()

            new_group_path = includes_dir / "brand-new.conf"
            assert new_group_path.exists()
            assert SshConfigStore(new_group_path).get("h1") is not None
            assert not any(severity == "warning" for _msg, severity in notifications)
