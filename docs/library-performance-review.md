# ghostty-textual performance adoption review

GhostCRT now pins the published ghostty-textual v0.0.4 wheel, adopting faster
colored output, selection, and hyperlink rendering while preserving its 60 Hz
output/scroll batching. The original review and measurements below compared
v0.0.2 with the library's performance working tree based on `eeaf9fa`.

The v0.0.4 release points to commit `45c2aa1fdf410b970e83a5ef60cb3af4cd556322`.
The downloaded wheel's SHA-256 matches the library handoff and `uv.lock`:
`22b8bedb2b2e3e85ddeb9f3bd5137df7b2593d1d19e3736756f4188211138ca5`.
Its Python sources match the frozen candidate used for the review and benchmarks.

## Consumer integration

The candidate introduces `TerminalView._flush_frame` for deferred feed rendering.
GhostCRT already used that name for its timer callback. Dynamic dispatch into
GhostCRT's override bypassed its 60 Hz scheduler: output arriving on successive
event-loop turns caused successive snapshots even before the frame deadline.

GhostCRT's timer callback is now `_flush_throttled_frame`. The library callback
clears its own pending handle and calls GhostCRT's `refresh_frame`, which combines
output, wheel events, and scrollbar changes into one timer. Forced refreshes remain
immediate. Regression coverage includes output across loop turns, mixed scrolling,
force refresh, reconnect/reset, and closing a pending frame.

Removing GhostCRT's scheduler would lose its scroll batching and rate limit.
The library's one-callback-per-loop-turn scheduling does not replace either.
Its large one-byte-feed speedup also does not represent GhostCRT's expected gain:
GhostCRT already coalesces frames and its PTY pump reads up to 4096 bytes at once.

Native style conversion caching, Rich style caching, per-row selection bounds,
reused hyperlink buffers, and the early synchronized-output check are inherited
through `TerminalView`/`Terminal` and require no separate consumer implementation.

## Measurements

Measured through `TerminalWidget` using `benchmarks/terminal_rendering.py` on
macOS 26.5.2 ARM64, Python 3.12.12, Textual 8.2.8, at 120 columns × 40 rows.
Each workload uses five warmups and 60 samples, with garbage collection enabled.
Baseline and candidate ran sequentially with the same installed dependencies.
Times include full native extraction, shadow-frame application, and rendering
every row. They exclude transport, scheduling delay, compositor work, and actual
terminal output; these are synthetic CPU measurements, not end-to-end latency.

| Workload | v0.0.2 median / p95 (ms) | Candidate median / p95 (ms) |
| --- | ---: | ---: |
| Plain | 6.055 / 6.345 | 6.161 / 6.695 |
| Plain, selected | 7.004 / 7.345 | 6.257 / 6.989 |
| Styled | 13.707 / 14.889 | 8.817 / 9.500 |
| Styled, selected | 14.676 / 15.499 | 8.797 / 9.551 |
| Alternating colors | 26.563 / 27.263 | 15.448 / 16.009 |
| Alternating colors, selected | 32.062 / 32.944 | 15.516 / 16.122 |
| Hyperlinked | 13.708 / 14.663 | 10.332 / 10.653 |
| Hyperlinked, selected | 14.571 / 15.069 | 10.268 / 10.921 |

Styled and alternating-color workloads reduce median CPU time by about 36–52%.
Hyperlinked output improves about 25–30%; plain extraction/rendering is essentially
unchanged. Alternating-color rendering still nearly consumes a 16.7 ms frame budget
before compositor work, so these measurements do not establish sustained 60 FPS.

For a stable comparison, the candidate source was copied into the ignored
`.ayder/performance-review/candidate/ghostty_textual` directory. SHA-256 of sorted
relative Python paths followed by file contents:
`ed55e06c1e26b7f2f6fa7fbc3167c6e28d0e56b46df76f21b90e1352372ba8d7`.

## Reproduce and adopt

Validation after the consumer fix: **360 passed, 8 skipped** against both the
installed v0.0.2 wheel and the frozen candidate source. Ruff checks passed for
`src`, `tests`, and `benchmarks`. The skipped tests require an external SSH test
server. These were pre-release checks; release validation is recorded below.

The final consumer review additionally covers synchronized-output release and
timeout through GhostCRT's timer. All 40 terminal tests pass against both versions
after adding those two cases. The library agent confirmed the callback rename and
existing refresh override are the intended integration; no upstream scheduling
API change is needed. No blocking library correction was found in this review.

From the repository root, validate the pinned release with:

```bash
uv sync --locked --all-extras
uv run --no-sync python benchmarks/terminal_rendering.py
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests benchmarks
uv build
```

For future candidate comparisons, use
`PYTHONPATH=../ghostty-textual/src:src .venv/bin/python benchmarks/terminal_rendering.py`.
The sibling working tree can change; use a frozen source copy when comparing
revisions. Avoid this override when validating the installed release artifact.

The v0.0.4 adoption updates the wheel URL in `pyproject.toml`, the generated
`uv.lock` entry and artifact hash, and the installation reference in `README.md`.
No unrelated dependency versions changed.

Release validation: **362 passed, 8 skipped** against the installed v0.0.4
GitHub wheel, with no candidate `PYTHONPATH` override. Ruff and diff checks passed.
Both GhostCRT distributions built successfully. Installing the built GhostCRT
wheel into a fresh environment resolved ghostty-textual v0.0.4 and passed CLI,
deferred feed/render, reset, and unmount smoke checks outside the source tree.
The eight skipped tests require the local SSH test server and sshpass.
