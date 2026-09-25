from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Collapsible, Input, OptionList, Tree

from ghostcrt.config.inventory import HostInventory
from ghostcrt.models import Host
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.screens.action_menu import ActionMenuScreen
from ghostcrt.ui.screens.host_edit import HostEditModal
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostList
from ghostcrt.ui.widgets.session_tabs import SessionTabs


class Preview(App):
    CSS_PATH = str(Path(__file__).parents[2] / 'src/ghostcrt/ui/compact.tcss')


def main_app(tmp_path):
    includes = tmp_path / 'includes'
    includes.mkdir()
    (includes / 'production.conf').write_text('Host web01\nHost db01\n')
    config = tmp_path / 'config'
    config.write_text(f'Include {includes}/*\n')
    class MainPreview(Preview):
        def on_mount(self):
            self.main_screen = MainScreen(None, HostInventory(config, includes))
            self.push_screen(self.main_screen)

    return MainPreview()


async def test_menu_navigation_disabled_actions_and_switching(tmp_path):
    app = main_app(tmp_path)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.click('#menu-hosts')
        options = app.screen.query_one(OptionList)
        assert options.highlighted_option.id == 'add'
        await pilot.press('down')
        assert options.highlighted_option.id == 'add'
        await pilot.press('right')
        await pilot.pause()
        assert app.screen._anchor_id == 'menu-vault'
        assert app.main_screen.focused.id == 'menu-vault'
        for key, target in [
            ('right', 'menu-session'),
            ('right', 'menu-hosts'),
            ('left', 'menu-session'),
            ('left', 'menu-vault'),
            ('left', 'menu-hosts'),
        ]:
            await pilot.press(key)
            await pilot.pause()
            assert app.screen._anchor_id == target
            assert app.main_screen.focused.id == target
            assert app.focused is app.screen.query_one(OptionList)
        await pilot.press('escape')
        assert app.screen is app.main_screen
        await pilot.click('#menu-hosts')
        await pilot.click(offset=(70, 15))
        assert app.screen is app.main_screen


async def test_menu_arrows_activate_choice():
    app = Preview()
    results = []
    async with app.run_test() as pilot:
        app.push_screen(ActionMenuScreen('Actions', [('one', 'One'), ('two', 'Two')]), results.append)
        await pilot.pause()
        await pilot.press('down', 'enter')
        assert results == ['two']


@pytest.mark.parametrize('size', [(120, 30), (80, 24)])
async def test_drawer_and_terminal_dimensions(tmp_path, size):
    app = main_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        screen = app.main_screen
        hosts = screen.query_one(HostList)
        assert hosts.size.height >= size[1] - 3
        tabs = screen.query_one(SessionTabs)
        await tabs.add_session(SshSession(alias='preview'))
        await pilot.pause()
        terminal = tabs.active_terminal
        assert terminal.has_focus
        assert terminal.size.width >= size[0] - (30 if size[0] >= 90 else 2)
        assert hosts.display == (size[0] >= 90)
        await pilot.press('ctrl+t')
        await pilot.pause()
        assert hosts.display
        assert screen.query_one(Tree).has_focus
        await pilot.press('escape')
        assert terminal.has_focus


async def test_filter_preserves_host_without_connecting(tmp_path):
    app = main_app(tmp_path)
    async with app.run_test() as pilot:
        hosts = app.screen.query_one(HostList)
        tree = hosts.query_one(Tree)
        tree.move_cursor(tree.root.children[0].children[1])
        await pilot.pause()
        hosts.query_one(Input).value = 'db'
        await pilot.pause()
        assert hosts.selected_host.alias == 'db01'
        assert tree.cursor_node.data.host.alias == 'db01'
        assert app.screen.query_one(SessionTabs).active_session is None


@pytest.mark.parametrize('theme', ['ansi-dark', 'ansi-light', 'textual-dark', 'monokai'])
async def test_editor_sections_and_fixed_actions(theme):
    app = Preview()
    async with app.run_test(size=(80, 24)) as pilot:
        app.theme = theme
        app.push_screen(HostEditModal(Host(alias='web01', extra={'proxycommand': 'ssh jump -W %h:%p'})))
        await pilot.pause()
        advanced = app.screen.query_one(Collapsible)
        assert advanced.collapsed
        assert app.screen.query_one('#proxy-command').region.height == 0
        assert app.screen.query_one('#save').region.bottom <= 24
        advanced.collapsed = False
        await pilot.pause()
        assert app.screen.query_one('#proxy-command').region.height == 1
        assert app.screen._build_host().extra['proxycommand'] == 'ssh jump -W %h:%p'
        assert app.screen.query_one('#save').region.bottom <= 24


async def test_host_menu_disables_actions_for_group_and_readonly_host(tmp_path):
    from ghostcrt.config.inventory import READONLY_GROUP

    app = main_app(tmp_path)
    async with app.run_test(size=(100, 28)) as pilot:
        config = tmp_path / 'config'
        config.write_text(config.read_text() + 'Host readonly-host\n')
        app.main_screen.refresh_hosts()
        await pilot.pause()
        tree = app.main_screen.query_one(Tree)
        for readonly in (False, True):
            group = next(n for n in tree.root.children if n.data.group == READONLY_GROUP)
            tree.move_cursor(group.children[0] if readonly else group)
            await pilot.pause()
            await pilot.click('#menu-hosts')
            options = app.screen.query_one(OptionList)
            assert options.get_option('edit').disabled
            assert options.get_option('delete').disabled
            assert options.get_option('copy').disabled is not readonly
            await pilot.press('down')
            assert options.highlighted_option.id == ('clone' if readonly else 'add')
            # Disabled rows must not activate even through direct selection.
            options.highlighted = options.get_option_index('edit')
            await pilot.press('enter')
            assert isinstance(app.screen, ActionMenuScreen)
            assert options.get_component_rich_style('option-list--option-disabled').dim
            await pilot.press('escape')
