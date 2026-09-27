"""Compare dependency versions in GhostCRT's extraction and row-rendering path.

Run with the project Python; use PYTHONPATH to select a candidate library.
This excludes transport, frame scheduling, the compositor, and terminal output.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time

import ghostty_textual
from ghostty_textual import Terminal

from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.widgets.terminal import TerminalWidget


def screen(workload: str, cols: int, rows: int) -> bytes:
    line = {
        "plain": b"x" * cols,
        "styled": b"\x1b[1;38;2;120;80;160m" + b"x" * cols + b"\x1b[0m",
        "alternating": b"\x1b[31mx\x1b[32mx" * (cols // 2)
        + (b"\x1b[31mx" if cols % 2 else b"")
        + b"\x1b[0m",
        "linked": b"\x1b]8;;https://example.com\x1b\\" + b"x" * cols + b"\x1b]8;;\x1b\\",
    }[workload]
    return b"\x1b[?25l" + b"".join(f"\x1b[{y + 1};1H".encode() + line for y in range(rows))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--cols", type=int, default=120)
    parser.add_argument("--rows", type=int, default=40)
    args = parser.parse_args()
    if min(args.samples, args.cols, args.rows) < 1:
        parser.error("samples and dimensions must be positive")
    results = []
    for workload in ("plain", "styled", "alternating", "linked"):
        for selected in (False, True):
            with Terminal(args.cols, args.rows) as terminal:
                terminal.feed(screen(workload, args.cols, args.rows))
                widget = TerminalWidget(SshSession("benchmark"), terminal=terminal)
                if selected:
                    widget._selection_anchor = (0, 0)
                    widget._selection_end = (args.cols - 1, args.rows - 1)
                values = []
                for index in range(args.samples + 5):
                    start = time.perf_counter()
                    frame = terminal.snapshot(force=True)
                    assert frame is not None
                    widget._apply_frame(frame)
                    for y in range(args.rows):
                        widget.render_line(y)
                    elapsed = (time.perf_counter() - start) * 1000
                    if index >= 5:
                        values.append(elapsed)
                results.append(
                    {
                        "workload": workload,
                        "selected": selected,
                        "median_ms": round(statistics.median(values), 3),
                        "p95_ms": round(sorted(values)[math.ceil(args.samples * 0.95) - 1], 3),
                    }
                )
    print(
        json.dumps(
            {
                "library": ghostty_textual.__file__,
                "cols": args.cols,
                "rows": args.rows,
                "samples": args.samples,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
