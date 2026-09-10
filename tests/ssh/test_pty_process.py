import asyncio
import sys

import pytest

from ghostcrt.ssh.pty_process import PtyProcess


@pytest.mark.asyncio
async def test_spawn_cat_echo():
    proc = await PtyProcess.spawn(
        [sys.executable, "-c", "import sys; print('hello-pty', flush=True)"]
    )
    data = b""
    for _ in range(50):
        chunk = await asyncio.wait_for(proc.read(1024), timeout=2)
        if not chunk:
            break
        data += chunk
        if b"hello-pty" in data:
            break
    assert b"hello-pty" in data
    code = await proc.wait()
    proc.close()
    assert code == 0


@pytest.mark.asyncio
async def test_write_to_cat():
    proc = await PtyProcess.spawn(["cat"])
    await proc.write(b"ping\n")
    data = b""
    for _ in range(20):
        chunk = await asyncio.wait_for(proc.read(1024), timeout=2)
        data += chunk
        if b"ping" in data:
            break
    assert b"ping" in data
    proc.terminate()
    await proc.wait()
    proc.close()


@pytest.mark.asyncio
async def test_concurrent_waiters_get_the_same_exit_code():
    proc = await PtyProcess.spawn([sys.executable, "-c", "raise SystemExit(7)"])
    try:
        first, second = await asyncio.gather(proc.wait(), proc.wait())
    finally:
        proc.close()

    assert first == second == 7


@pytest.mark.asyncio
async def test_spawn_sets_terminal_size_before_child_starts():
    proc = await PtyProcess.spawn(
        [
            sys.executable,
            "-c",
            "import os; s=os.get_terminal_size(); print(s.lines, s.columns)",
        ],
        rows=37,
        cols=111,
    )
    try:
        data = b""
        while chunk := await asyncio.wait_for(proc.read(1024), timeout=2):
            data += chunk
        assert await proc.wait() == 0
    finally:
        proc.close()

    assert b"37 111" in data
