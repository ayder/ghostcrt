from pathlib import Path

import pytest
from textual.app import App

from ghostcrt.ui.screens.unlock import UnlockScreen
from ghostcrt.vault.vault import Vault


class UnlockApp(App):
    def __init__(self, vault_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.vault_path = vault_path
        self.result = None

    def on_mount(self) -> None:
        self.push_screen(UnlockScreen(self.vault_path), self._done)

    def _done(self, vault) -> None:
        self.result = vault
        self.exit()


@pytest.mark.asyncio
async def test_create_vault_flow(tmp_path: Path):
    path = tmp_path / "vault.enc"
    app = UnlockApp(path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#password")
        await pilot.press(*list("goodpass1"))
        # focus confirm
        await pilot.click("#confirm")
        await pilot.press(*list("goodpass1"))
        await pilot.click("#submit")
        await pilot.pause()
    assert Vault.exists(path)
    assert Vault.unlock(path, "goodpass1") is not None


@pytest.mark.asyncio
async def test_wrong_key_stays(tmp_path: Path):
    path = tmp_path / "vault.enc"
    Vault.create(path, "right-key").save()
    app = UnlockApp(path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#password")
        await pilot.press(*list("wrong-key"))
        await pilot.click("#submit")
        await pilot.pause()
        err = app.screen.query_one("#unlock-error")
        assert "Wrong" in str(err.render())
        # app still running on unlock screen
        assert app.result is None
        await pilot.press("escape")
