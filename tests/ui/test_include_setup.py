from textual.app import App

from ghostcrt.config.include_bootstrap import include_is_configured, include_line
from ghostcrt.ui.screens.include_setup import IncludeSetupModal


def build(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host bastion\n")
    inc = tmp_path / "includes"
    inc.mkdir()
    return cfg, inc


async def test_add_it_for_me_prepends_the_line_and_backs_up(tmp_path):
    cfg, inc = build(tmp_path)
    result: list[bool] = []

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(IncludeSetupModal(cfg, inc), result.append)

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#include-add")
        await pilot.pause()

    assert result == [True]
    assert cfg.read_text().splitlines()[0] == include_line(inc)
    assert (tmp_path / "config.bak").read_text() == "Host bastion\n"
    assert include_is_configured(cfg, inc)


async def test_later_leaves_the_file_untouched(tmp_path):
    cfg, inc = build(tmp_path)
    result: list[bool] = []

    class TestApp(App[None]):
        def on_mount(self):
            self.push_screen(IncludeSetupModal(cfg, inc), result.append)

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#include-later")
        await pilot.pause()

    assert result == [False]
    assert cfg.read_text() == "Host bastion\n"
    assert not (tmp_path / "config.bak").exists()


async def test_main_screen_offers_setup_only_when_the_include_is_missing(tmp_path):
    from ghostcrt.config.inventory import HostInventory
    from ghostcrt.ui.screens.main import MainScreen

    class FakeVault:
        def get(self, alias):
            return None

    cfg, inc = build(tmp_path)

    def run(config_path):
        class TestApp(App[None]):
            def on_mount(self):
                self.push_screen(MainScreen(FakeVault(), HostInventory(config_path, inc)))

        return TestApp()

    # Missing: the modal is offered.
    app = run(cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, IncludeSetupModal)

    # Present: no modal.
    cfg.write_text(f"{include_line(inc)}\n\nHost bastion\n")
    app = run(cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
