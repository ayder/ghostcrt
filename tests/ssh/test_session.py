import asyncio
import sys

import pytest

from ghostcrt.models import SessionState
from ghostcrt.ssh.session import SshSession


@pytest.mark.asyncio
async def test_session_emits_raw_process_output():
    session = SshSession(alias="local")
    outputs: list[bytes] = []
    session.on_output = outputs.append
    await session.start([sys.executable, "-c", "print('hi-session')"])
    for _ in range(100):
        await asyncio.sleep(0.05)
        if b"hi-session" in b"".join(outputs):
            break
    assert b"hi-session" in b"".join(outputs)
    await session.close()
    assert session.state == SessionState.DISCONNECTED
    assert session.exit_code is not None


@pytest.mark.asyncio
async def test_reconnect_restarts_the_transport():
    session = SshSession(alias="x")
    outputs: list[bytes] = []
    resets: list[str] = []
    session.on_output = outputs.append
    await session.start([sys.executable, "-c", "print('one')"])
    for _ in range(100):
        await asyncio.sleep(0.05)
        if session.state == SessionState.DISCONNECTED:
            break
    async def before_start() -> None:
        assert session.state == SessionState.DISCONNECTED
        resets.append("reset")

    await session.reconnect(
        [sys.executable, "-c", "print('two')"],
        before_start=before_start,
    )
    for _ in range(100):
        await asyncio.sleep(0.05)
        if b"two" in b"".join(outputs):
            break
    assert b"one" in b"".join(outputs)
    assert b"two" in b"".join(outputs)
    assert resets == ["reset"]
    await session.close()


@pytest.mark.asyncio
async def test_close_terminates_live_process_without_pump_deadlock():
    session = SshSession(alias="long-running")
    await session.start([sys.executable, "-c", "import time; time.sleep(60)"])

    await asyncio.wait_for(session.close(), timeout=3)

    assert session.state == SessionState.DISCONNECTED
    assert session.exit_code is not None


@pytest.mark.asyncio
async def test_concurrent_close_is_idempotent():
    session = SshSession(alias="close-race")
    await session.start([sys.executable, "-c", "import time; time.sleep(60)"])

    await asyncio.wait_for(
        asyncio.gather(session.close(), session.close()),
        timeout=3,
    )

    assert session.state == SessionState.DISCONNECTED


@pytest.mark.asyncio
async def test_disposed_session_cannot_be_reconnected():
    session = SshSession(alias="disposed")
    await session.start([sys.executable, "-c", "import time; time.sleep(60)"])
    await session.close()

    with pytest.raises(RuntimeError, match="closed"):
        await session.reconnect([sys.executable, "-c", "print('unexpected')"])


@pytest.mark.asyncio
async def test_pump_preserves_non_utf8_bytes_for_the_terminal_library():
    session = SshSession(alias="raw-bytes")
    outputs: list[bytes] = []
    session.on_output = outputs.append
    await session.start(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'\\xff\\x00alive')",
        ]
    )

    for _ in range(100):
        await asyncio.sleep(0.05)
        if b"alive" in b"".join(outputs):
            break

    assert b"\xff\x00alive" in b"".join(outputs)
    await session.close()
