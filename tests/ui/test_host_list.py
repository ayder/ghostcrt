from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Tree

from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.ui.widgets.host_list import HostList


def inventory(tmp_path: Path) -> HostInventory:
    cfg = tmp_path / "config"
    cfg.write_text("Host bastion\n")
    inc = tmp_path / "includes"
    inc.mkdir()
    (inc / "production.conf").write_text("Host srv1 srv2\n    User jorn\n")
    (inc / "company.conf").write_text("Host *.company.com\n    User jornw\n")
    return HostInventory(cfg, inc)


class HostListApp(App[None]):
    def compose(self) -> ComposeResult:
        yield HostList()


def group_names(tree: Tree) -> list[str]:
    return [str(node.label).split()[0] for node in tree.root.children]


def leaves(tree: Tree, group: str) -> list[str]:
    node = next(n for n in tree.root.children if str(n.label).startswith(group))
    return [str(child.label) for child in node.children]


async def test_groups_become_top_level_nodes(tmp_path):
    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(inventory(tmp_path).groups())
        await pilot.pause()

        assert group_names(host_list.query_one(Tree)) == [
            "company",
            "production",
            READONLY_GROUP,
        ]


async def test_hosts_are_leaves_showing_the_alias_only(tmp_path):
    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(inventory(tmp_path).groups())
        await pilot.pause()

        assert leaves(host_list.query_one(Tree), "production") == ["srv1", "srv2"]


async def test_patterns_appear_but_are_not_connectable(tmp_path):
    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(inventory(tmp_path).groups())
        await pilot.pause()

        tree = host_list.query_one(Tree)
        node = next(n for n in tree.root.children if str(n.label).startswith("company"))
        pattern = node.children[0]

        assert "*.company.com" in str(pattern.label)
        assert pattern.data is not None
        assert pattern.data.connectable is False


async def test_filter_hides_groups_with_no_match(tmp_path):
    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(inventory(tmp_path).groups())
        await pilot.pause()

        host_list.query_one("#host-filter").value = "srv1"
        await pilot.pause()

        tree = host_list.query_one(Tree)
        assert group_names(tree) == ["production"]
        assert leaves(tree, "production") == ["srv1"]


async def test_selecting_a_leaf_reports_its_host_and_group(tmp_path):
    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(inventory(tmp_path).groups())
        await pilot.pause()

        tree = host_list.query_one(Tree)
        node = next(n for n in tree.root.children if str(n.label).startswith("production"))
        tree.select_node(node.children[0])
        await pilot.pause()

        assert host_list.selected_host is not None
        assert host_list.selected_host.alias == "srv1"
        assert host_list.selected_group == "production"


async def test_readonly_group_is_marked(tmp_path):
    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(inventory(tmp_path).groups())
        await pilot.pause()

        tree = host_list.query_one(Tree)
        node = next(n for n in tree.root.children if str(n.label).startswith(READONLY_GROUP))

        assert "[RO]" in str(node.label)


async def test_shadowed_host_is_annotated(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host bastion\n    User bob\n")
    inc = tmp_path / "includes"
    inc.mkdir()
    (inc / "production.conf").write_text("Host bastion\n    User alice\n")

    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_groups(HostInventory(cfg, inc).groups())
        await pilot.pause()

        label = leaves(host_list.query_one(Tree), READONLY_GROUP)[0]

        assert label.startswith("bastion")
        assert "⊘ production" in label
        # Must survive the 28-column sidebar without truncating.
        assert len(label) < 24


async def test_set_hosts_still_works_as_a_flat_list(tmp_path):
    from ghostcrt.models import Host

    app = HostListApp()
    async with app.run_test() as pilot:
        host_list = app.query_one(HostList)
        host_list.set_hosts([Host(alias="solo", hostname="10.0.0.1")])
        await pilot.pause()

        tree = host_list.query_one(Tree)
        assert leaves(tree, "hosts") == ["solo"]
