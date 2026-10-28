"""Exercise an installed distribution outside the source tree (wheel or sdist)."""

from importlib.resources import files

from ghostty_textual import Terminal, TerminalView

from ghostcrt.ui.widgets.terminal import TerminalWidget

assert issubclass(TerminalWidget, TerminalView)
assert files("ghostcrt").joinpath("ui/compact.tcss").is_file()

with Terminal(20, 3, scrollback=100) as terminal:
    terminal.feed(b"release smoke")
    frame = terminal.snapshot()
    assert frame is not None
    assert "".join(cell.text for cell in frame.row_patches[0].cells).startswith("release smoke")
    terminal.feed(b"\r\nline" * 20)
    terminal.scroll_to_top()
    assert not terminal.viewport.at_bottom
    terminal.scroll_to_bottom()
    assert terminal.viewport.at_bottom
