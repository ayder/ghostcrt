"""The session tab strip: a divider rule under the tabs, and a thin focused tab.

The design (ghostcrt design system, SessionTabs card) sets the strip off from the
terminal with the same ANSI bright-black rule as the host sidebar, and draws the
active tab as a thin rectangle in the block-cursor colour while the strip has
focus, instead of the reversed block cursor with solid end caps.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.segment import Segment
from textual.app import App
from textual.geometry import Region
from textual.widgets import Static, TabPane
from textual.widgets._tabbed_content import ContentTabs

from ghostcrt.ui.widgets.session_tab import SessionTab, SessionTabbedContent
from ghostcrt.ui.widgets.session_tabs import SessionTabs

ANSI_BRIGHT_BLACK = 8
# Hand-resolved $block-cursor-background: ANSI 7 under ansi-dark, ANSI 4 under
# ansi-light (Textual's ANSI themes), and #0178D4 under textual-dark.
CURSOR_COLOUR = {"ansi-dark": 7, "ansi-light": 4, "textual-dark": "#0178d4"}


class TabStripApp(App[None]):
    CSS_PATH = str(Path(__file__).parents[2] / "src/ghostcrt/ui/compact.tcss")

    def compose(self):
        yield SessionTabs(id="sessions")


async def open_tabs(app: TabStripApp, pilot, theme: str) -> SessionTab:
    app.theme = theme
    tabs = app.query_one(SessionTabbedContent)
    for index, title in enumerate(["web-01", "db-01", "lab-03 [exit 255]"]):
        pane = TabPane(title, Static("ops@web-01:~$"), id=f"s{index}")
        await tabs.add_session_pane(pane, title)
    tabs.active = "s0"
    await pilot.pause()
    return next(tab for tab in app.query(SessionTab) if tab.pane_id == "s0")


def row(widget, y: int) -> list[Segment]:
    (strip,) = widget.render_lines(Region(0, y, widget.outer_size.width, 1))
    return [segment for segment in strip if segment.text]


def text(segments: list[Segment]) -> str:
    return "".join(segment.text for segment in segments)


def colour_matches(color, expected) -> bool:
    if isinstance(expected, int):
        return color is not None and color.number == expected
    return color is not None and color.triplet is not None and color.triplet.hex == expected


@pytest.mark.parametrize("theme", ["ansi-dark", "ansi-light", "textual-dark"])
async def test_a_rule_separates_the_tab_strip_from_the_terminal(theme):
    app = TabStripApp()
    async with app.run_test(size=(80, 12)) as pilot:
        await open_tabs(app, pilot, theme)
        strip = app.query_one(ContentTabs)

        assert strip.outer_size.height == 2
        rule = row(strip, 1)
        assert set(text(rule)) == {"─"}
        assert len(text(rule)) == strip.outer_size.width

        pane = app.query_one("#s0", TabPane)
        assert pane.region.y == strip.region.y + 2


@pytest.mark.parametrize("theme", ["ansi-dark", "ansi-light"])
async def test_the_tab_rule_is_the_sidebar_grey_not_the_focus_ring(theme):
    app = TabStripApp()
    async with app.run_test(size=(80, 12)) as pilot:
        await open_tabs(app, pilot, theme)
        rule = row(app.query_one(ContentTabs), 1)

        assert all(segment.style.color.number == ANSI_BRIGHT_BLACK for segment in rule)


@pytest.mark.parametrize("theme", ["ansi-dark", "ansi-light", "textual-dark"])
async def test_the_focused_active_tab_is_a_thin_cursor_coloured_rectangle(theme):
    app = TabStripApp()
    async with app.run_test(size=(80, 12)) as pilot:
        active = await open_tabs(app, pilot, theme)
        width_before = active.outer_size.width
        app.query_one(ContentTabs).focus()
        await pilot.pause()

        cells = row(active, 0)
        assert text(cells).startswith("▏") and text(cells).endswith("▕")
        assert active.outer_size.width == width_before

        label = [segment for segment in cells[1:-1] if segment.text.strip()]
        assert "web-01" in text(label)
        for segment in label:
            style = segment.style
            assert style.bold and style.overline and style.underline
            assert not style.reverse
            assert colour_matches(style.color, CURSOR_COLOUR[theme])
        for segment in cells:
            assert not colour_matches(segment.style.bgcolor, CURSOR_COLOUR[theme])


@pytest.mark.parametrize("theme", ["ansi-dark", "ansi-light", "textual-dark"])
async def test_the_active_tab_stays_reversed_while_the_terminal_has_focus(theme):
    app = TabStripApp()
    async with app.run_test(size=(80, 12)) as pilot:
        active = await open_tabs(app, pilot, theme)
        app.set_focus(None)
        await pilot.pause()

        cells = row(active, 0)
        assert text(cells).startswith(" web-01") and text(cells).endswith("× ")
        label = [segment for segment in cells if segment.text.strip()]
        assert all(segment.style.bold and segment.style.reverse for segment in label)
        assert not any(segment.style.overline for segment in cells)
