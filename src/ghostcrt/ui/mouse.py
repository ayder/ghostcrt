"""Hand the host terminal's mouse back and forth.

Textual's driver captures the mouse unconditionally on start-up
(``\\x1b[?1000h ?1003h ?1015h ?1006h``, ``textual/drivers/linux_driver.py``),
which disables iTerm/Terminal.app native selection for as long as the app runs.
``App.run(mouse=False)`` opts out, but only at start-up and at the cost of wheel
scrolling, tab clicks and in-pane drag-select (see ADR-0002 and ADR-0005).

There is no public runtime switch, so this drives the private driver API and
degrades to a no-op wherever it is missing -- the headless test driver has
``_mouse`` but no enable/disable pair, and a future Textual could rename it.
``tests/ui/test_mouse_toggle.py`` guards the names.
"""

from __future__ import annotations

from typing import Any


def _supports_toggle(driver: Any) -> bool:
    return (
        driver is not None
        and hasattr(driver, "_mouse")
        and callable(getattr(driver, "_enable_mouse_support", None))
        and callable(getattr(driver, "_disable_mouse_support", None))
    )


def mouse_is_captured(driver: Any) -> bool:
    """Whether Textual currently owns the host terminal's mouse."""
    return bool(getattr(driver, "_mouse", False))


def toggle_mouse_capture(driver: Any) -> bool | None:
    """Flip mouse capture; return the new state, or None if unsupported.

    The two branches are deliberately asymmetric. Textual's own
    ``_enable_mouse_support`` and ``_disable_mouse_support`` both open with
    ``if not self._mouse: return``, so ``_mouse`` has to be True *across* each
    call. Clearing the flag first would make the disable a silent no-op and
    leave the terminal captured.
    """
    if not _supports_toggle(driver):
        return None

    if driver._mouse:
        driver._disable_mouse_support()
        driver._mouse = False
        return False

    driver._mouse = True
    driver._enable_mouse_support()
    return True
