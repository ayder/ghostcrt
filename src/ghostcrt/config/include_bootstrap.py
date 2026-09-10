from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


def include_line(includes: Path) -> str:
    target = str(includes.expanduser().absolute() / "*.conf")
    if any(c in target for c in "\n\r\x00"):
        raise ValueError("Invalid Include path.")
    if any(c.isspace() or c in '#"\\' for c in target):
        target = '"' + target.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"Include {target}"


def include_is_configured(ssh_config: Path, includes: Path) -> bool:
    """Require complete coverage before any options, Host, Match or other Include.

    An earlier Include may itself introduce options or conditional scope. Be
    conservative instead of claiming group precedence without expanding it.
    """
    try:
        text = ssh_config.read_text()
    except OSError:
        return False
    want = includes.expanduser().absolute()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"(?i)^include(?:\s*=\s*|\s+)(.*)$", line)
        if match is None:
            return False
        try:
            arguments = shlex.split(match[1], comments=True)
        except ValueError:
            return False
        for argument in arguments:
            expanded = Path(os.path.expanduser(argument))
            if not expanded.is_absolute():
                expanded = Path.home() / ".ssh" / expanded
            # Earlier files could change both scope and first-value precedence.
            return expanded.parent.absolute() == want and expanded.name in ("*", "*.conf")
        return False
    return False


def add_include(ssh_config: Path, includes: Path) -> Path | None:
    """Prepend a leading Include after taking a backup of the original file."""
    line = include_line(includes)
    if ssh_config.is_file():
        if include_is_configured(ssh_config, includes):
            return None
        original = ssh_config.read_text()
        backup = ssh_config.with_suffix(ssh_config.suffix + ".bak")
        backup.write_text(original)
        ssh_config.write_text(f"{line}\n\n{original}")
        return backup
    ssh_config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ssh_config.write_text(f"{line}\n")
    return None
