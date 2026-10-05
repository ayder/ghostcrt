"""ctrl+o hands the mouse back to the host terminal, and takes it again.

Textual's driver grabs the host terminal's mouse unconditionally
(`\x1b[?1000h ?1003h ?1015h ?1006h`, `linux_driver.py:128`), which kills
iTerm/Terminal.app native selection for as long as ghostcrt runs. There is
no public runtime switch -- `App.run(mouse=False)` is start-up only -- so the
toggle drives `Driver._mouse` and the enable/disable pair directly.

That is private API, so `test_textual_still_exposes_the_private_mouse_api`
guards it: if a Textual upgrade renames any of it, that test fails loudly
instead of ctrl+o silently doing nothing.
"""

from __future__ import annotations

from pathlib import Path
from types import MethodType

import pytest
from ghostty_textual import MouseEvent as NativeMouseEvent
from ghostty_textual import Terminal
from textual._xterm_parser import XTermParser
from textual.app import App
from textual.binding import Binding
from textual.drivers.headless_driver import HeadlessDriver
from textual.drivers.linux_driver import LinuxDriver

from ghostcrt.app import GhostCRTApp
from ghostcrt.config.inventory import HostInventory
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.mouse import mouse_is_captured, toggle_mouse_capture
from ghostcrt.ui.screens.main import MainScreen
from ghostcrt.ui.widgets.host_list import HostTree
from ghostcrt.ui.widgets.session_tabs import SessionTabs


class RecordingDriver:
    """Stands in for a real terminal driver, recording call order.

    Order matters: Textual's own `_enable_mouse_support` starts with
    `if not self._mouse: return`, so `_mouse` has to be True *before* the call
    or enabling silently does nothing.
    """

    def __init__(self, mouse: bool = True) -> None:
        self._mouse = mouse
        self.calls: list[tuple[str, bool]] = []

    def _enable_mouse_support(self) -> None:
        self.calls.append(("enable", self._mouse))

    def _disable_mouse_support(self) -> None:
        self.calls.append(("disable", self._mouse))


def test_releasing_the_mouse_disables_reporting_and_records_the_new_state():
    driver = RecordingDriver(mouse=True)

    captured = toggle_mouse_capture(driver)

    assert captured is False
    assert driver.calls == [("disable", True)]
    assert driver._mouse is False


def test_disable_is_called_before_the_flag_is_cleared():
    """Textual's `_disable_mouse_support` early-returns when `_mouse` is False."""
    driver = RecordingDriver(mouse=True)

    toggle_mouse_capture(driver)

    assert driver.calls[0] == ("disable", True), (
        "clearing _mouse first would make Textual's own early-return swallow "
        "the disable, leaving the terminal still captured"
    )


def test_recapturing_sets_the_flag_before_enabling():
    """Textual's `_enable_mouse_support` early-returns when `_mouse` is False."""
    driver = RecordingDriver(mouse=False)

    captured = toggle_mouse_capture(driver)

    assert captured is True
    assert driver.calls == [("enable", True)], (
        "enabling before setting _mouse would hit Textual's early-return and "
        "never write the enable sequences"
    )
    assert driver._mouse is True


def test_toggling_twice_returns_to_the_starting_state():
    driver = RecordingDriver(mouse=True)

    toggle_mouse_capture(driver)
    toggle_mouse_capture(driver)

    assert driver._mouse is True
    assert [name for name, _ in driver.calls] == ["disable", "enable"]


async def test_toggle_is_inert_on_a_driver_without_mouse_support():
    """HeadlessDriver has `_mouse` but no enable/disable pair."""
    # Driver.__init__ calls get_running_loop(), hence the async test.
    driver = HeadlessDriver(App(), size=(80, 24))

    assert toggle_mouse_capture(driver) is None
    assert toggle_mouse_capture(None) is None


def test_mouse_is_captured_reports_driver_state():
    assert mouse_is_captured(RecordingDriver(mouse=True)) is True
    assert mouse_is_captured(RecordingDriver(mouse=False)) is False
    assert mouse_is_captured(None) is False


async def test_textual_still_exposes_the_private_mouse_api():
    """Upgrade guard: fail loudly rather than let ctrl+o become a no-op."""
    import inspect

    from textual.drivers.linux_driver import LinuxDriver

    assert hasattr(HeadlessDriver(App(), size=(80, 24)), "_mouse")
    assert callable(LinuxDriver._enable_mouse_support)
    assert callable(LinuxDriver._disable_mouse_support)
    assert callable(LinuxDriver._enable_mouse_pixels)

    # toggle_mouse_capture's call ordering exists only because of these early
    # returns. If Textual drops them the ordering comment stops making sense.
    for method in (LinuxDriver._enable_mouse_support, LinuxDriver._disable_mouse_support):
        assert "if not self._mouse" in inspect.getsource(method)


def binding_for(key: str) -> Binding | None:
    for binding in GhostCRTApp.BINDINGS:
        if isinstance(binding, Binding) and binding.key == key:
            return binding
    return None


def test_ctrl_o_toggles_the_mouse_and_beats_the_terminal_pane_to_the_key():
    binding = binding_for("ctrl+o")

    assert binding is not None, "ctrl+o must be bound to release the mouse"
    assert binding.action == "toggle_mouse"
    assert binding.priority, (
        "without priority the focused TerminalWidget forwards ctrl+o to the remote "
        "process instead of toggling"
    )
    assert binding_for("f2") is None


def test_ctrl_m_is_never_bound_because_the_terminal_sends_it_as_enter():
    assert binding_for("ctrl+m") is None


async def test_pressing_ctrl_o_reaches_the_driver(tmp_home):
    """End to end: the key press must actually drive the real toggle.

    The app keeps its real driver -- swapping it out breaks Textual internals.
    Only the two methods HeadlessDriver lacks are supplied.
    """
    app = GhostCRTApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        driver = app._driver
        calls: list[tuple[str, bool]] = []
        driver._enable_mouse_support = lambda: calls.append(("enable", driver._mouse))
        driver._disable_mouse_support = lambda: calls.append(("disable", driver._mouse))
        driver._mouse = True

        await pilot.press("ctrl+o")
        await pilot.pause()

        assert calls == [("disable", True)]
        assert driver._mouse is False

        await pilot.press("ctrl+o")
        await pilot.pause()

        assert [name for name, _ in calls] == ["disable", "enable"]
        assert driver._mouse is True


class NativeProtocolDriver:
    """Run real Textual control writes through Ghostty's native terminal core."""

    _enable_mouse_support = LinuxDriver._enable_mouse_support
    _disable_mouse_support = LinuxDriver._disable_mouse_support
    _enable_mouse_pixels = LinuxDriver._enable_mouse_pixels

    def __init__(self, terminal):
        self._mouse = True
        self._mouse_pixels = False
        self.terminal = terminal

    def write(self, data):
        self.terminal.feed(data.encode())

    def flush(self):
        pass


def negotiate_mouse_protocol(driver, terminal, pixels, cell_size):
    cell_width, cell_height = cell_size
    native = terminal._native
    size = native.ffi.new(
        'GhosttyMouseEncoderSize*',
        {
            'size': native.ffi.sizeof('GhosttyMouseEncoderSize'),
            'screen_width': 120 * cell_width,
            'screen_height': 40 * cell_height,
            'cell_width': cell_width,
            'cell_height': cell_height,
        },
    )
    native.lib.ghostty_mouse_encoder_setopt(
        terminal._mouse_encoder, native.lib.GHOSTTY_MOUSE_ENCODER_OPT_SIZE, size
    )
    driver._enable_mouse_support()
    parser = XTermParser()
    if pixels:
        driver._enable_mouse_pixels()
        list(parser.feed(f'\x1b[48;40;120;{40 * cell_height};{120 * cell_width}t'))
        assert parser.mouse_pixels
    return parser


@pytest.mark.parametrize('pixels', [False, True], ids=['cells', 'pixels'])
@pytest.mark.parametrize('cell_size', [(10, 20), (12, 24)])
def test_mouse_roundtrip_preserves_negotiated_coordinates(pixels, cell_size):
    with Terminal(120, 40) as terminal:
        driver = NativeProtocolDriver(terminal)
        parser = negotiate_mouse_protocol(driver, terminal, pixels, cell_size)
        physical = NativeMouseEvent(20.5 * cell_size[0], 11.5 * cell_size[1])
        original = terminal.encode_mouse(physical)
        assert original is not None
        event, = parser.feed(original.decode())
        assert (event.x, event.y) == (20, 11)

        for _ in range(3):
            assert toggle_mouse_capture(driver) is False
            assert terminal.encode_mouse(physical) is None
            assert toggle_mouse_capture(driver) is True
            packet = terminal.encode_mouse(physical)
            assert packet is not None
            event, = parser.feed(packet.decode())
            assert (event.x, event.y) == (20, 11)
            assert packet == original


@pytest.mark.parametrize('pixels', [False, True], ids=['cells', 'pixels'])
async def test_recaptured_protocol_click_reaches_host_group(tmp_path, pixels):
    includes = tmp_path / 'includes'
    includes.mkdir()
    (includes / 'production.conf').write_text('Host synthetic-host\n')
    config = tmp_path / 'config'
    config.write_text(f'Include {includes}/*\n')

    class RoutingApp(App):
        CSS_PATH = str(Path(__file__).parents[2] / 'src/ghostcrt/ui/compact.tcss')
        BINDINGS = GhostCRTApp.BINDINGS
        action_toggle_mouse = GhostCRTApp.action_toggle_mouse

        def on_mount(self):
            self.main_screen = MainScreen(None, HostInventory(config, includes))
            self.push_screen(self.main_screen)

    app = RoutingApp()
    app.theme = 'nord'
    with Terminal(120, 40) as terminal:
        async with app.run_test(size=(120, 40)) as pilot:
            tree = app.screen.query_one(HostTree)
            group = next(node for node in tree.root.children if node.data.group == 'production')
            tree.move_cursor(group.children[0])
            await pilot.pause()
            driver = app._driver
            driver._mouse = True
            driver._mouse_pixels = False
            driver.write = lambda data: terminal.feed(data.encode())
            for method in ('_enable_mouse_support', '_disable_mouse_support', '_enable_mouse_pixels'):
                setattr(driver, method, MethodType(getattr(LinuxDriver, method), driver))
            parser = negotiate_mouse_protocol(driver, terminal, pixels, (10, 20))
            await pilot.press('ctrl+o')
            assert driver._mouse is False
            await pilot.press('ctrl+o')
            assert driver._mouse is True

            x = tree.region.x + 8
            y = tree.region.y + group.line
            for action in ('press', 'release'):
                packet = terminal.encode_mouse(NativeMouseEvent(x * 10 + 5, y * 20 + 10, action))
                assert packet is not None
                for event in parser.feed(packet.decode()):
                    driver.process_message(event)
            await pilot.pause()
            assert app.screen is app.main_screen
            assert app.focused is tree
            assert tree.cursor_node is group
            assert app._exception is None

            tabs = app.main_screen.query_one(SessionTabs)
            await tabs.add_session(SshSession('synthetic-session'))
            await pilot.pause()
            target = tabs.active_terminal
            tree.focus()
            await pilot.pause()
            x = target.region.x + 5
            y = target.region.y + 3
            for action in ('press', 'release'):
                packet = terminal.encode_mouse(NativeMouseEvent(x * 10 + 5, y * 20 + 10, action))
                assert packet is not None
                for event in parser.feed(packet.decode()):
                    driver.process_message(event)
            await pilot.pause()
            assert app.screen is app.main_screen
            assert app.focused is target
            assert app._exception is None


def test_pixel_driver_without_restore_support_is_unchanged():
    driver = RecordingDriver(mouse=False)
    driver._mouse_pixels = True
    assert toggle_mouse_capture(driver) is None
    assert driver._mouse is False
    assert driver.calls == []
