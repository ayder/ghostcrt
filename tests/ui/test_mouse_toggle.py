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

from textual.app import App
from textual.binding import Binding
from textual.drivers.headless_driver import HeadlessDriver

from ghostcrt.app import GhostCRTApp
from ghostcrt.ui.mouse import mouse_is_captured, toggle_mouse_capture


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
