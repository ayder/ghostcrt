from ghostcrt.app import GhostCRTApp


async def test_default_theme_is_a_current_textual_ansi_theme(tmp_home):
    app = GhostCRTApp()

    async with app.run_test():
        assert app.theme == "ansi-dark"
        assert app.theme in app.available_themes


async def test_custom_config_reaches_main_screen(tmp_home):
    from ghostcrt.ui.screens.main import MainScreen
    from ghostcrt.vault.vault import Vault

    cfg = tmp_home / "custom-config"
    inc = tmp_home / ".config/ghostcrt/includes"
    cfg.write_text(f"Include {inc}/*.conf\n")
    app = GhostCRTApp(ssh_config=cfg)
    async with app.run_test() as pilot:
        app._on_unlocked(Vault.create(tmp_home / "vault.enc", "synthetic-master"))
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
        assert app.screen.ssh_config == cfg
        assert app.screen.inventory.ssh_config == cfg


async def test_main_screen_lists_hosts_from_both_sources(tmp_path):
    from textual.app import App

    from ghostcrt.config.inventory import HostInventory
    from ghostcrt.ui.screens.main import MainScreen
    from ghostcrt.ui.widgets.host_list import HostList

    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    # Include already configured, so the setup modal stays out of the way.
    cfg.write_text(f"Include {inc}/*\n\nHost bastion\n")
    (inc / "production.conf").write_text("Host srv1 srv2\n    User jorn\n")

    class FakeVault:
        def get(self, alias):
            return None

    inventory = HostInventory(cfg, inc)

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(MainScreen(FakeVault(), inventory))

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        host_list = app.screen.query_one(HostList)
        aliases = sorted(h.alias for h in host_list._hosts)

    assert aliases == ["bastion", "srv1", "srv2"]


async def test_main_screen_starts_with_host_tree_focused(tmp_path):
    from textual.app import App
    from textual.widgets import Tree

    from ghostcrt.config.inventory import HostInventory
    from ghostcrt.ui.screens.main import MainScreen

    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text(f"Include {inc}/*\n")
    (inc / "production.conf").write_text("Host srv1\n")

    class FakeVault:
        def get(self, alias):
            return None

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(MainScreen(FakeVault(), HostInventory(cfg, inc)))

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.focused is app.screen.query_one("#host-tree", Tree)


async def test_refresh_hosts_picks_up_a_group_file_added_on_disk(tmp_path):
    from textual.app import App

    from ghostcrt.config.inventory import HostInventory
    from ghostcrt.ui.screens.main import MainScreen
    from ghostcrt.ui.widgets.host_list import HostList

    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    # Include already configured, so the setup modal stays out of the way.
    cfg.write_text(f"Include {inc}/*\n\nHost bastion\n")

    class FakeVault:
        def get(self, alias):
            return None

    inventory = HostInventory(cfg, inc)

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(MainScreen(FakeVault(), inventory))

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert screen.inventory is inventory

        (inc / "production.conf").write_text("Host srv9\n    User jorn\n")
        screen.refresh_hosts()
        await pilot.pause()

        aliases = sorted(h.alias for h in screen.query_one(HostList)._hosts)

    assert aliases == ["bastion", "srv9"]
