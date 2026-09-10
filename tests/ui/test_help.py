from textual.widgets import Static

from ghostcrt.app import GhostCRTApp
from ghostcrt.ui.screens.help import HelpScreen


def test_help_uses_readable_control_key_syntax():
    shortcuts = dict(HelpScreen.SHORTCUTS)

    assert "ctrl+n" in shortcuts
    assert "ctrl+w" in shortcuts
    assert "ctrl+q" in shortcuts
    assert "ctrl+o" in shortcuts
    assert all(not key.startswith("^") for key in shortcuts)


async def test_ctrl_h_opens_and_closes_help(tmp_home):
    app = GhostCRTApp()

    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("ctrl+h")
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)
        rendered_keys = {
            str(widget.content) for widget in app.screen.query(".help-key").results(Static)
        }
        assert {"ctrl+n", "ctrl+w", "ctrl+q", "ctrl+o"} <= rendered_keys

        await pilot.press("ctrl+h")
        await pilot.pause()

        assert not isinstance(app.screen, HelpScreen)


def test_footer_only_shows_readable_help_binding():
    visible = [binding for binding in GhostCRTApp.BINDINGS if binding.show]

    assert len(visible) == 1
    assert visible[0].key == "ctrl+h"
    assert visible[0].key_display == "ctrl+h"
