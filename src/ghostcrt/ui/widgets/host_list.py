from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.strip import Strip
from textual.widgets import Input, Tree
from textual.widgets.tree import TreeNode

from ghostcrt.models import Host, HostGroup
from ghostcrt.ui.widgets.fuzzy import filter_hosts


@dataclass
class HostNode:
    """Payload attached to every tree node.

    `connectable` is False for group nodes and for wildcard stanzas, which are
    settings that apply to matching hosts rather than places to connect.
    """

    host: Host | None
    group: str
    connectable: bool


class HostTree(Tree[HostNode]):
    """A full-row cursor with a marker that survives palette changes."""

    def render_label(self, node: TreeNode[HostNode], base_style: Style, style: Style) -> Text:
        label = super().render_label(node, base_style, style)
        if node.data and node.data.connectable:
            label = Text("> " if node == self.cursor_node else "  ", style=style) + label
        return label

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if y + self.scroll_offset.y == self.cursor_line:
            cursor = self.get_component_rich_style("tree--cursor")
            strip = Strip(
                Segment(segment.text, (segment.style or Style()) + cursor, segment.control)
                for segment in strip
            )
        return strip


class HostList(Vertical):
    """Sidebar host inventory, grouped as a tree, with fuzzy filter."""

    DEFAULT_CSS = """
    HostList {
        width: 28;
        min-width: 20;
        height: 1fr;
        /* Literal ANSI grey, not $border: $border is Textual's focus-ring token
           (ansi_magenta under an ANSI palette). The grey is a concrete colour
           that stays a neutral divider under every palette. */
        border-right: solid ansi_bright_black;
    }
    HostList #host-filter {
        dock: top;
        margin: 0 0 1 0;
    }
    HostList #host-tree {
        height: 1fr;
    }
    """

    class HostSelected(Message):
        def __init__(self, host: Host) -> None:
            super().__init__()
            self.host = host

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._groups: list[HostGroup] = []
        self._hosts: list[Host] = []
        self._selected: Host | None = None
        self._selected_group: str | None = None

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter hosts…", id="host-filter")
        tree = HostTree("hosts", id="host-tree")
        tree.show_root = False
        yield tree

    def set_groups(self, groups: list[HostGroup]) -> None:
        self._groups = list(groups)
        self._hosts = [host for group in self._groups for host in group.hosts]
        self._rebuild()

    def set_hosts(self, hosts: list[Host]) -> None:
        """Flat compatibility path: render everything as one unnamed group."""
        self.set_groups([HostGroup(name="hosts", path=Path(), hosts=list(hosts))])

    def _query(self) -> str:
        try:
            return self.query_one("#host-filter", Input).value
        except Exception:
            return ""

    def _rebuild(self) -> None:
        try:
            tree = self.query_one("#host-tree", Tree)
        except Exception:
            return
        selected_key = (self._selected_group, self._selected.alias) if self._selected else None
        collapsed = {n.data.group for n in tree.root.children if n.data and not n.is_expanded}
        self._selected = None
        self._selected_group = None
        tree.clear()
        restore = None
        query = self._query()
        for group in self._groups:
            matches = filter_hosts(group.hosts, query)
            # Patterns are settings, not search results — hide them while filtering.
            patterns = group.patterns if not query else []
            if not matches and not patterns:
                continue
            suffix = ""
            if not group.writable:
                suffix = " [RO]"
            if group.error:
                suffix = " [!]"
            node = tree.root.add(
                f"{group.name}{suffix}",
                data=HostNode(host=None, group=group.name, connectable=False),
                expand=bool(query) or group.name not in collapsed,
            )
            for host in matches:
                label = host.alias
                shadow = group.shadowed_by.get(host.alias)
                if shadow:
                    # The sidebar is 28 columns; a prose annotation truncates
                    # to nothing useful, so mark it compactly instead.
                    label = f"{host.alias}  ⊘ {shadow}"
                leaf = node.add_leaf(
                    label,
                    data=HostNode(host=host, group=group.name, connectable=True),
                )
                if selected_key == (group.name, host.alias):
                    restore = leaf
            for pattern in patterns:
                node.add_leaf(
                    pattern.alias,
                    data=HostNode(host=pattern, group=group.name, connectable=False),
                )

        if restore is not None:
            tree.move_cursor(restore)
            self.call_after_refresh(lambda: tree.move_cursor(restore))
            self._selected = restore.data.host
            self._selected_group = restore.data.group

    def on_key(self, event: events.Key) -> None:
        if event.key == "down" and self.query_one("#host-filter", Input).has_focus:
            event.stop()
            event.prevent_default()
            self.focus_list()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "host-filter":
            self._rebuild()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node is not self.query_one(Tree).cursor_node:
            return
        data = event.node.data
        if data is not None and data.connectable and data.host is not None:
            self._selected = data.host
            self._selected_group = data.group
        else:
            self._selected = None
            self._selected_group = None

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if data is None or not data.connectable or data.host is None:
            return
        self._selected = data.host
        self._selected_group = data.group
        self.post_message(self.HostSelected(data.host))

    @property
    def selected_host(self) -> Host | None:
        return self._selected

    @property
    def selected_group(self) -> str | None:
        return self._selected_group

    def focus_filter(self) -> None:
        self.query_one("#host-filter", Input).focus()

    def focus_list(self) -> None:
        self.query_one("#host-tree", Tree).focus()
