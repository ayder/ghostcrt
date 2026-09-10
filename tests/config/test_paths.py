from pathlib import Path

from ghostcrt.config.paths import (
    config_dir,
    ensure_config_dir,
    ensure_includes_dir,
    includes_dir,
    settings_path,
    ssh_config_path,
    vault_path,
)


def test_paths_under_home_config(tmp_home: Path):
    assert config_dir() == tmp_home / ".config" / "ghostcrt"
    assert vault_path() == config_dir() / "vault.enc"
    assert settings_path() == config_dir() / "settings.toml"
    assert ssh_config_path() == tmp_home / ".ssh" / "config"


def test_ensure_config_dir_mode(tmp_home: Path):
    d = ensure_config_dir()
    assert d.is_dir()
    assert (d.stat().st_mode & 0o777) == 0o700


def test_includes_dir_lives_under_the_ghostcrt_config_dir(tmp_home: Path):
    assert includes_dir() == config_dir() / "includes"


def test_ensure_includes_dir_creates_it_private(tmp_home: Path):
    path = ensure_includes_dir()

    assert path.is_dir()
    assert (path.stat().st_mode & 0o777) == 0o700


def test_ensure_includes_dir_is_idempotent(tmp_home: Path):
    first = ensure_includes_dir()
    (first / "keep.conf").write_text("Host keep\n")

    second = ensure_includes_dir()

    assert second == first
    assert (second / "keep.conf").read_text() == "Host keep\n"
