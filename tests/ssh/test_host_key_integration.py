"""Real OpenSSH/sshpass tests; set GHOSTCRT_TEST_SSH_PORT for a local test sshd.

The server must accept ghostcrt / synthetic-test-password. Each test uses its
own SSH config and known_hosts; no developer SSH configuration is accessed.
"""

import asyncio
import os
import shutil
from contextlib import asynccontextmanager

import pytest
from textual.app import App

from ghostcrt.models import SessionState
from ghostcrt.ssh.command import build_ssh_command
from ghostcrt.ssh.session import SshSession
from ghostcrt.ui.widgets.session_tabs import SessionTabs
from ghostcrt.ui.widgets.terminal import TerminalWidget

PASSWORD = "synthetic-test-password"


@pytest.fixture
def ssh_config(tmp_path):
    port = os.environ.get("GHOSTCRT_TEST_SSH_PORT")
    if not port or not shutil.which("sshpass"):
        pytest.skip("requires local test sshd (GHOSTCRT_TEST_SSH_PORT) and sshpass")
    config = tmp_path / "ssh config"
    config.write_text(
        f"Host regression\n"
        f" HostName 127.0.0.1\n Port {int(port)}\n User ghostcrt\n"
        f' UserKnownHostsFile "{tmp_path / "known_hosts"}"\n'
        " GlobalKnownHostsFile /dev/null\n StrictHostKeyChecking ask\n"
        " HostKeyAlgorithms ssh-ed25519\n PubkeyAuthentication no\n"
        " PreferredAuthentications password\n ControlMaster no\n ControlPath none\n"
        " LogLevel QUIET\n ConnectTimeout 5\n"
    )
    return config


@asynccontextmanager
async def connection(config, password=PASSWORD):
    session = SshSession("regression")
    output = bytearray()
    session.on_output = output.extend
    try:
        await start(session, config, password=password)
        yield session, output
    finally:
        await session.close()


async def start(session, config, *, password=PASSWORD, reconnect=False):
    cmd = build_ssh_command("regression", password, config=config)
    method = session.reconnect if reconnect else session.start
    await method(
        cmd.argv,
        pass_fds=cmd.pass_fds,
        password=cmd.password,
        write_fd=cmd.write_fd,
        read_fd=cmd.read_fd,
    )


async def wait_for_output(output, text):
    async with asyncio.timeout(10):
        while text not in output:
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("password", [None, PASSWORD])
async def test_first_host_prompt_acceptance_login_and_reconnect(ssh_config, password):
    async with connection(ssh_config, password) as (session, output):
        await wait_for_output(output, b"(yes/no/[fingerprint])?")
        assert b"SHA256:" in output
        assert not (ssh_config.parent / "known_hosts").exists()
        assert session.state == SessionState.CONNECTED
        await session.send(b"yes\n")
        if password is None:
            await wait_for_output(output, b"password:")
            await session.send(PASSWORD.encode() + b"\n")
        await wait_for_output(output, b"$ ")
        assert (ssh_config.parent / "known_hosts").read_text()
        assert PASSWORD.encode() not in output
        assert b"Permission denied" not in output
        await session.send(b"exit\n")
        await asyncio.wait_for(session._pump_task, 5)
        assert session.exit_code == 0

        output.clear()
        await start(session, ssh_config, password=password, reconnect=True)
        if password is None:
            await wait_for_output(output, b"password:")
            await session.send(PASSWORD.encode() + b"\n")
        await wait_for_output(output, b"$ ")
        assert b"authenticity" not in output


async def test_declining_host_key_does_not_start_password_login(ssh_config):
    async with connection(ssh_config) as (session, output):
        await wait_for_output(output, b"(yes/no/[fingerprint])?")
        await session.send(b"no\n")
        await asyncio.wait_for(session._pump_task, 5)
        assert session.exit_code == 255
        assert b"Host key verification failed" in output
        assert b"password:" not in output
        assert not (ssh_config.parent / "known_hosts").exists()


async def test_closing_during_host_prompt_terminates_probe(ssh_config):
    async with connection(ssh_config) as (session, output):
        await wait_for_output(output, b"(yes/no/[fingerprint])?")
        await asyncio.wait_for(session.close(), 3)
        assert session.state == SessionState.DISCONNECTED
        assert not (ssh_config.parent / "known_hosts").exists()


async def test_ctrl_c_cancels_host_prompt_without_a_traceback(ssh_config):
    async with connection(ssh_config) as (session, output):
        await wait_for_output(output, b"(yes/no/[fingerprint])?")
        await session.send(b"\x03")
        await asyncio.wait_for(session._pump_task, 5)
        assert session.exit_code == 130
        assert b"Traceback" not in output
        assert not (ssh_config.parent / "known_hosts").exists()


async def test_host_prompt_is_visible_and_answerable_in_session_tab(ssh_config):
    class TestApp(App):
        def compose(self):
            yield SessionTabs()

    app = TestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        session = SshSession("regression")
        await app.query_one(SessionTabs).add_session(session)
        terminal = app.query_one(TerminalWidget)
        try:
            await start(session, ssh_config)

            def rendered():
                return "\n".join(
                    terminal.render_line(row).text for row in range(terminal.size.height)
                )

            async with asyncio.timeout(10):
                while "(yes/no/[fingerprint])?" not in rendered():
                    await pilot.pause()
            assert "SHA256:" in rendered()
            terminal.focus()
            await pilot.press("y", "e", "s", "enter")
            async with asyncio.timeout(10):
                while "$ " not in rendered():
                    await pilot.pause()
            assert (ssh_config.parent / "known_hosts").read_text()
        finally:
            await session.close()


async def test_changed_key_is_rejected(ssh_config):
    key = ssh_config.parent / "unrelated_key"
    proc = await asyncio.create_subprocess_exec(
        "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)
    )
    assert await proc.wait() == 0
    public_key = key.with_suffix(".pub").read_text()
    (ssh_config.parent / "known_hosts").write_text(
        f"[127.0.0.1]:{os.environ['GHOSTCRT_TEST_SSH_PORT']} {public_key}"
    )
    async with connection(ssh_config) as (session, output):
        await asyncio.wait_for(session._pump_task, 5)
        assert session.exit_code == 255
        assert b"REMOTE HOST IDENTIFICATION HAS CHANGED" in output
        assert b"password:" not in output


async def test_strict_host_key_policy_is_preserved(ssh_config):
    ssh_config.write_text(
        ssh_config.read_text().replace("StrictHostKeyChecking ask", "StrictHostKeyChecking yes")
    )
    async with connection(ssh_config) as (session, output):
        await asyncio.wait_for(session._pump_task, 5)
        assert session.exit_code == 255
        assert b"Host key verification failed" in output
        assert b"(yes/no" not in output
