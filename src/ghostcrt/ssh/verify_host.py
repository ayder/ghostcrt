"""Verify host keys on the tab's TTY before handing authentication to sshpass.

This is also a standalone child-process entry point; keep imports stdlib-only.
The password stays in its inherited pipe until sshpass reads it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# OpenSSH emits this terminal error after host verification when the server
# rejects the initial "none" authentication request. Other exit-255 failures
# (including rejected/changed host keys) must not start the password login.
_AUTH_DENIED = re.compile(rb"[^\r\n]+: Permission denied \([\w,@.-]*\)\.\r?\n?\Z")


def verification_command(ssh_argv: list[str]) -> list[str]:
    # build_ssh_command always supplies "ssh -tt [options] -- alias". Put probe
    # settings first because OpenSSH uses the first value for each -o option.
    options = (
        "BatchMode=no",
        "PreferredAuthentications=none",
        "NumberOfPasswordPrompts=0",
        "ControlMaster=no",
        "ControlPath=none",
        "ClearAllForwardings=yes",
        "PermitLocalCommand=no",
        "RemoteCommand=none",
        "SessionType=default",
        "ForkAfterAuthentication=no",
        # Ensure the authentication result is available even with LogLevel QUIET.
        "LogLevel=ERROR",
    )
    argv = [ssh_argv[0], "-T"]
    for option in options:
        argv.extend(["-o", option])
    # If a server permits unauthenticated access, finish the probe immediately.
    return [*argv, *ssh_argv[2:], "exit 0"]


def verify_host(ssh_argv: list[str]) -> int:
    result = subprocess.run(
        verification_command(ssh_argv),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        # Host-key questions belong in the tab, even if the desktop environment
        # normally forces a graphical SSH_ASKPASS program.
        env={**os.environ, "SSH_ASKPASS_REQUIRE": "never"},
    )
    denied = _AUTH_DENIED.search(result.stderr) if result.returncode == 255 else None
    if result.returncode == 0 or denied is not None:
        return 0
    sys.stderr.buffer.write(result.stderr)
    sys.stderr.buffer.flush()
    return result.returncode if result.returncode > 0 else 128 - result.returncode


def main() -> int:
    password_fd, *ssh_argv = sys.argv[1:]
    code = verify_host(ssh_argv)
    if code:
        return code
    # Exec preserves the session's PID, PTY and inherited password descriptor.
    os.execvp("sshpass", ["sshpass", "-d", password_fd, *ssh_argv])
    return 127  # exec only returns on failure


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except OSError as exc:
        print(f"Unable to start SSH: {exc}", file=sys.stderr)
        raise SystemExit(127) from exc
