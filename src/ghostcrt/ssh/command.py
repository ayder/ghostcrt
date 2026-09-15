from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ghostcrt.config.ssh_config import is_concrete_alias


@dataclass
class SshCommand:
    argv: list[str]
    pass_fds: tuple[int, ...]
    password: str | None = field(repr=False)
    write_fd: int | None
    read_fd: int | None = None

    def close_pipe(self) -> None:
        for fd in (self.read_fd, self.write_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.read_fd = self.write_fd = None


def build_ssh_command(
    connect_alias: str, password: str | None, *, config: Path | None = None
) -> SshCommand:
    if not is_concrete_alias(connect_alias):
        raise ValueError("Invalid SSH destination alias.")
    ssh_argv = ["ssh", "-tt"]
    if config is not None:
        ssh_argv.extend(["-F", str(config.expanduser().absolute())])
    ssh_argv.extend(["--", connect_alias])
    if not password:
        return SshCommand(
            argv=ssh_argv,
            pass_fds=(),
            password=None,
            write_fd=None,
            read_fd=None,
        )
    r, w = os.pipe()
    os.set_inheritable(r, True)
    os.set_inheritable(w, False)
    # Verify the host interactively before sshpass can swallow its prompt.
    # Run the helper by path so this also works from an installed wheel.
    helper = Path(__file__).with_name("verify_host.py")
    argv = [sys.executable, str(helper), str(r), *ssh_argv]
    return SshCommand(
        argv=argv,
        pass_fds=(r,),
        password=password,
        write_fd=w,
        read_fd=r,
    )
