"""The layout CSS must draw every colour from the active Textual palette.

Two rules, both learned the hard way and both only observable under an ANSI
palette -- which is what ghostcrt ships as its default (``ansi-dark``):

1. ``$surface``/``$panel`` resolve to *transparent* under an ANSI palette, so a
   floating overlay painted with them has no background at all and blends into
   whatever it is covering.
2. ``$border`` is Textual's *focus ring* token (``design.py`` hardcodes it to
   ``ansi_magenta`` for ANSI palettes). Used as a static layout divider it
   paints the sidebar edge bright magenta.

The RGB palettes a user can switch to must keep following their own palette, so
the ANSI handling is an ``&:ansi`` refinement rather than a hardcoded colour.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest
from textual.app import App
from textual.color import Color

from ghostcrt.config.inventory import HostInventory
from ghostcrt.models import Host
from ghostcrt.ui.screens.action_menu import ActionMenuScreen
from ghostcrt.ui.screens.group_picker import GroupPickerScreen
from ghostcrt.ui.screens.help import HelpScreen
from ghostcrt.ui.screens.host_edit import HostEditModal
from ghostcrt.ui.screens.include_setup import IncludeSetupModal
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.screens.unlock import UnlockScreen
from ghostcrt.ui.screens.vault_edit import VaultEditModal
from ghostcrt.ui.widgets.host_list import HostList

ANSI_PALETTES = ["ansi-dark", "ansi-light"]
RGB_PALETTES = ["textual-dark", "monokai"]
ALL_PALETTES = ANSI_PALETTES + RGB_PALETTES

ANSI_BRIGHT_BLACK = 8


class FakeVault:
    def get(self, alias: str) -> None:
        return None


def scratch_inventory() -> HostInventory:
    root = Path(tempfile.mkdtemp())
    includes = root / "includes"
    includes.mkdir()
    (includes / "production.conf").write_text("Host srv1\n  HostName 10.0.0.1\n")
    (root / "config").write_text(f"Include {includes}/*\n")
    return HostInventory(root / "config", includes)


class ConformanceApp(App[None]):
    def on_mount(self) -> None:
        self.push_screen(MainScreen(FakeVault(), scratch_inventory()))


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


# Each overlay, as (box id, factory). Factories, not instances: a Screen can
# only be mounted once, and every parametrised case mounts a fresh app.
OVERLAYS = [
    ("#action-menu-box", lambda: ActionMenuScreen("srv1", [("connect", "Connect")])),
    ("#group-picker-box", lambda: GroupPickerScreen(["production"])),
    ("#help-box", HelpScreen),
    ("#host-edit-box", lambda: HostEditModal(Host(alias="srv1"), is_new=False)),
    ("#include-box", lambda: IncludeSetupModal(_tmp() / "config", _tmp() / "includes")),
    ("#vault-edit-box", lambda: VaultEditModal("srv1")),
    ("#unlock-box", lambda: UnlockScreen(_tmp() / "vault.json")),
]


async def overlay_and_backdrop(theme: str, box_id: str, make_screen) -> tuple:
    """Resolved background of an overlay box and of the screen behind it."""
    app = ConformanceApp()
    async with app.run_test(size=(120, 30)) as pilot:
        app.theme = theme
        await pilot.pause()
        backdrop = app.screen.background_colors[1]
        app.push_screen(make_screen())
        await pilot.pause()
        await pilot.pause()
        box = app.screen.query_one(box_id)
        return box.background_colors[1], backdrop


@pytest.mark.parametrize("theme", ALL_PALETTES)
@pytest.mark.parametrize("box_id,make_screen", OVERLAYS, ids=[o[0] for o in OVERLAYS])
async def test_overlay_boxes_are_opaque_against_the_content_behind_them(
    theme, box_id, make_screen
):
    box_bg, backdrop = await overlay_and_backdrop(theme, box_id, make_screen)

    assert box_bg != backdrop, (
        f"{box_id} under {theme} paints the same background as the screen behind it "
        f"({box_bg!r}); the overlay has no visible box."
    )


@pytest.mark.parametrize("theme", RGB_PALETTES)
async def test_overlay_boxes_still_follow_the_palette_surface_on_rgb_themes(theme):
    """The ANSI fix must not hardcode a colour that overrides a chosen palette."""
    app = ConformanceApp()
    async with app.run_test(size=(120, 30)) as pilot:
        app.theme = theme
        await pilot.pause()
        surface = app.get_css_variables()["surface"]
        app.push_screen(ActionMenuScreen("srv1", [("connect", "Connect")]))
        await pilot.pause()
        await pilot.pause()
        box_bg = app.screen.query_one("#action-menu-box").background_colors[1]

        assert box_bg.hex.lower() == surface.lower()


async def sidebar_divider(theme: str):
    app = ConformanceApp()
    async with app.run_test(size=(120, 30)) as pilot:
        app.theme = theme
        await pilot.pause()
        assert not app.screen.has_class("compact"), "120 cols should not be compact"
        edge, color = app.screen.query_one(HostList).styles.border_right
        return edge, color, app.get_css_variables()["border"]


@pytest.mark.parametrize("theme", ALL_PALETTES)
async def test_sidebar_divider_does_not_reuse_the_focus_ring_token(theme):
    """`$border` is the focus ring; a permanent divider must not borrow it."""
    edge, color, focus_ring = await sidebar_divider(theme)

    assert edge == "solid"
    # Compare parsed Colors: `Color.css` renders RGB as "rgb(1,120,212)" while
    # the variable is "#0178D4", so comparing the strings never matches.
    assert color != Color.parse(focus_ring), (
        f"the host sidebar divider under {theme} is painted with $border "
        f"({focus_ring}), Textual's focus-ring colour"
    )


async def test_sidebar_divider_is_neutral_grey_under_the_ansi_palette():
    """Concretely: the default theme must not draw a magenta sidebar edge."""
    _, color, _ = await sidebar_divider("ansi-dark")

    assert color.ansi == ANSI_BRIGHT_BLACK


def test_no_stylesheet_hardcodes_an_rgb_colour():
    """Guard: colours come from the palette, never from a literal in the CSS."""
    offenders = []
    for path in Path("src/ghostcrt/ui").rglob("*.py"):
        for block in re.findall(r'(?:DEFAULT_)?CSS\s*=\s*"""(.*?)"""', path.read_text(), re.DOTALL):
            for literal in re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", block):
                offenders.append(f"{path}: {literal}")

    assert offenders == []
