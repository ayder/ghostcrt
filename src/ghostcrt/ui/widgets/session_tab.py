from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.await_complete import AwaitComplete
from textual.geometry import Region
from textual.message import Message
from textual.strip import Strip
from textual.widgets import ContentSwitcher, TabbedContent, TabPane
from textual.widgets._tabbed_content import ContentTab, ContentTabs

# Top and bottom of the focused tab's outline. Textual 8.2.8 parses `overline` in
# CSS but its style type drops it, so it is added to the rendered cells instead,
# edges included, which also closes the rectangle's corners.
OUTLINE = Style(overline=True, underline=True)


class SessionTab(ContentTab):
    """A session title with a close target that does not activate the tab."""

    def render_lines(self, crop: Region) -> list[Strip]:
        lines = super().render_lines(crop)
        if not self._outlined():
            return lines
        return [
            Strip(
                [Segment(text, (style or Style()) + OUTLINE, control) for text, style, control in line],
                line.cell_length,
            )
            for line in lines
        ]

    def _outlined(self) -> bool:
        """The active tab while the strip has focus: compact.tcss draws its sides."""
        strip = next((node for node in self.ancestors if isinstance(node, ContentTabs)), None)
        return self.has_class("-active") and strip is not None and strip.has_focus

    class CloseRequested(Message):
        def __init__(self, pane_id: str) -> None:
            super().__init__()
            self.pane_id = pane_id

    def __init__(self, title: str, pane_id: str) -> None:
        super().__init__(title, pane_id)
        self.pane_id = pane_id
        self.set_title(title)

    def set_title(self, title: str) -> None:
        label = Text(title)
        label.append("  ×", Style(meta={"session_close": True}))
        self.label = label

    def _on_click(self, event: events.Click) -> None:
        event.stop()
        event.prevent_default()
        if event.style.meta.get("session_close"):
            self.post_message(self.CloseRequested(self.pane_id))
        else:
            super()._on_click()


class SessionTabbedContent(TabbedContent):
    def add_session_pane(self, pane: TabPane, title: str) -> AwaitComplete:
        # Textual 8.2.8 has no tab factory hook. Keep its ContentTabs and
        # ContentSwitcher so activation/removal retain standard tab behavior.
        assert pane.id is not None
        pane.display = False
        return AwaitComplete(
            self.get_child_by_type(ContentTabs).add_tab(SessionTab(title, pane.id)),
            self.get_child_by_type(ContentSwitcher).mount(pane),
        )
