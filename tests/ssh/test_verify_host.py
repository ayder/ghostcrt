import subprocess
import sys

import pytest

from ghostcrt.ssh import verify_host


@pytest.mark.parametrize(
    ("code", "stderr", "expected"),
    [
        (255, b"user@host: Permission denied (publickey,password).\r\n", 0),
        (255, b"user@host: Permission denied (keyboard-interactive).\n", 0),
        (0, b"", 0),
        (255, b"Host key verification failed.\r\n", 255),
        (255, b"WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\n", 255),
        (255, b"ssh: connect to host host port 22: Connection refused\n", 255),
        (255, b"Permission denied\n", 255),
        (255, b"user@host: Permission denied (password).\nHost key verification failed.\n", 255),
        (1, b"user@host: Permission denied (password).\n", 1),
        (-2, b"", 130),
    ],
)
def test_probe_only_proceeds_after_host_verification(monkeypatch, capfd, code, stderr, expected):
    def run(argv, **kwargs):
        assert kwargs["env"]["SSH_ASKPASS_REQUIRE"] == "never"
        assert "pass_fds" not in kwargs  # No password descriptor is passed to the probe.
        return subprocess.CompletedProcess(argv, code, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run)
    assert verify_host.verify_host(["ssh", "-tt", "--", "host"]) == expected
    assert capfd.readouterr().err == (stderr.decode() if expected else "")


def test_probe_preserves_destination_and_config_without_starting_session_features():
    argv = verify_host.verification_command(
        ["ssh", "-tt", "-F", "/config with spaces", "--", "host"]
    )
    assert argv[:2] == ["ssh", "-T"]
    assert argv[-5:] == ["-F", "/config with spaces", "--", "host", "exit 0"]
    assert "PreferredAuthentications=none" in argv
    assert "ClearAllForwardings=yes" in argv
    assert "PermitLocalCommand=no" in argv
    assert "ControlPath=none" in argv
    assert "RemoteCommand=none" in argv
    assert not any("StrictHostKeyChecking" in arg or "KnownHostsFile" in arg for arg in argv)


@pytest.mark.parametrize("probe_code", [0, 255, 130])
def test_password_login_runs_only_after_successful_probe(monkeypatch, probe_code):
    ssh_argv = ["ssh", "-tt", "-F", "/config", "--", "host"]
    monkeypatch.setattr(sys, "argv", ["verify_host.py", "42", *ssh_argv])
    monkeypatch.setattr(verify_host, "verify_host", lambda argv: probe_code)
    calls = []
    monkeypatch.setattr(verify_host.os, "execvp", lambda *args: calls.append(args))

    code = verify_host.main()

    if probe_code == 0:
        assert calls == [("sshpass", ["sshpass", "-d", "42", *ssh_argv])]
    else:
        assert calls == []
        assert code == probe_code
