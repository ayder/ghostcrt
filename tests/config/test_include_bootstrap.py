import pytest

from ghostcrt.config.include_bootstrap import (
    add_include,
    include_is_configured,
    include_line,
)


def test_include_line_points_at_the_includes_directory(tmp_path):
    line = include_line(tmp_path / "includes")

    assert line == f"Include {tmp_path / 'includes'}/*.conf"


@pytest.mark.parametrize(
    "directive",
    [
        "Include {inc}/*",
        "Include {inc}/*.conf",
        "include {inc}/*",
        "Include   {inc}/*",
    ],
)
def test_detects_an_existing_include_in_any_valid_form(tmp_path, directive):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text(directive.format(inc=inc) + "\nHost a\n")

    assert include_is_configured(cfg, inc) is True


def test_detects_a_home_relative_include(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    inc = tmp_path / ".config" / "ghostcrt" / "includes"
    inc.mkdir(parents=True)
    cfg = tmp_path / "config"
    cfg.write_text("Include ~/.config/ghostcrt/includes/*\n")

    assert include_is_configured(cfg, inc) is True


def test_unrelated_include_does_not_count(tmp_path):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text(f"Include {tmp_path / 'other'}/*\n")

    assert include_is_configured(cfg, inc) is False


def test_add_include_prepends_and_backs_up(tmp_path):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text("Host bastion\n    User bob\n")

    backup = add_include(cfg, inc)

    lines = cfg.read_text().splitlines()
    assert lines[0] == include_line(inc)
    assert "Host bastion" in cfg.read_text()
    assert backup is not None
    assert backup.read_text() == "Host bastion\n    User bob\n"
    assert include_is_configured(cfg, inc) is True


def test_add_include_is_idempotent(tmp_path):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "config"
    cfg.write_text("Host bastion\n")

    add_include(cfg, inc)
    add_include(cfg, inc)

    assert cfg.read_text().count("Include") == 1


def test_add_include_creates_ssh_config_when_absent(tmp_path):
    inc = tmp_path / "includes"
    inc.mkdir()
    cfg = tmp_path / "ssh" / "config"

    backup = add_include(cfg, inc)

    assert backup is None
    assert cfg.read_text().strip() == include_line(inc)
    assert (cfg.parent.stat().st_mode & 0o777) == 0o700
