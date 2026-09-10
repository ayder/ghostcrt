from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

SshOptionValue = str | list[str]


@dataclass
class Host:
    alias: str
    aliases: list[str] = field(default_factory=list)
    hostname: str | None = None
    user: str | None = None
    port: int | None = None
    identity_file: SshOptionValue | None = None
    # A list value represents a directive that occurs more than once in the
    # same Host block (for example, multiple LocalForward entries).
    extra: dict[str, SshOptionValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.aliases:
            self.aliases = [self.alias]


@dataclass
class HostGroup:
    """A group of hosts, backed by one file: an include file we own, or
    ~/.ssh/config, which we only ever read."""

    name: str
    path: Path
    hosts: list[Host] = field(default_factory=list)
    patterns: list[Host] = field(default_factory=list)
    writable: bool = True
    error: str | None = None
    # alias -> name of the group that wins over this one for that alias
    shadowed_by: dict[str, str] = field(default_factory=dict)


@dataclass
class Secret:
    alias: str
    password: str

    def __repr__(self) -> str:
        return f"Secret(alias={self.alias!r}, password=***)"


@dataclass
class AppSettings:
    theme: str = "ansi-dark"
    layout_preset: str = "default"


class SessionState(Enum):
    CONNECTING = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()
