from __future__ import annotations

from pathlib import Path


def config_dir() -> Path:
    return Path.home() / ".config" / "ghostcrt"


def ensure_config_dir() -> Path:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    d.chmod(0o700)
    return d


def includes_dir() -> Path:
    """Directory of group files ghostcrt owns and writes."""
    return config_dir() / "includes"


def ensure_includes_dir() -> Path:
    d = includes_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    d.chmod(0o700)
    return d


def vault_path() -> Path:
    return config_dir() / "vault.enc"


def settings_path() -> Path:
    return config_dir() / "settings.toml"


def ssh_config_path() -> Path:
    return Path.home() / ".ssh" / "config"
