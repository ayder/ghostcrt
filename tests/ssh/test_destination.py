import pytest

from ghostcrt.config.ssh_config import is_concrete_alias
from ghostcrt.ssh.command import build_ssh_command


@pytest.mark.parametrize("password", [None, "synthetic-password"])
def test_custom_config_applies_with_either_authentication_method(tmp_path, password):
    cfg = tmp_path / "config with spaces"
    cmd = build_ssh_command("sample", password, config=cfg)
    try:
        start = cmd.argv.index("ssh")
        assert cmd.argv[start:] == ["ssh", "-tt", "-F", str(cfg), "--", "sample"]
        assert "synthetic-password" not in repr(cmd)
    finally:
        cmd.close_pipe()


@pytest.mark.parametrize("alias", ["", "-V", "-oProxyCommand=test", "two words", "a\nHost b", "*"])
@pytest.mark.parametrize("password", [None, "synthetic-password"])
def test_invalid_alias_cannot_allocate_pipe_or_spawn(alias, password, monkeypatch):
    assert not is_concrete_alias(alias)

    def forbidden():
        pytest.fail("invalid alias allocated a password pipe")

    monkeypatch.setattr("ghostcrt.ssh.command.os.pipe", forbidden)
    with pytest.raises(ValueError):
        build_ssh_command(alias, password)
