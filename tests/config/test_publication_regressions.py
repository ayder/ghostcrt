import shutil
import subprocess

import pytest

from ghostcrt.config.include_bootstrap import add_include, include_is_configured, include_line
from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigError, SshConfigStore
from ghostcrt.models import Host


def test_rejected_rename_does_not_delete_host_on_later_save(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("")
    inc = tmp_path / "includes"
    inc.mkdir()
    group = inc / "production.conf"
    group.write_text("Host a\n HostName a.example\nHost b\n HostName b.example\n")
    inv = HostInventory(cfg, inc)
    with pytest.raises(SshConfigError):
        inv.update("production", "a", Host(alias="b"))
    inv.add("production", Host(alias="c"))
    assert SshConfigStore(group).get("a").hostname == "a.example"


def test_failed_save_rolls_back_pending_changes(tmp_path, monkeypatch):
    path = tmp_path / "config"
    path.write_text("Host a\n User original\n")
    store = SshConfigStore(path)
    store.update("a", Host(alias="a", user="unsaved"))
    with monkeypatch.context() as patch:
        patch.setattr(
            "ghostcrt.config.ssh_config.os.replace",
            lambda *args: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(SshConfigError):
            store.save()
    store.add(Host(alias="b"))
    store.save()
    assert SshConfigStore(path).get("a").user == "original"


def test_edit_preserves_stanza_order_and_repeated_identity_files(tmp_path):
    path = tmp_path / "config"
    path.write_text(
        "Host a\n User alice\n IdentityFile ~/.ssh/one\n"
        " IdentityFile ~/.ssh/two\nHost *\n User default\n"
    )
    store = SshConfigStore(path)
    host = store.get("a")
    assert host.identity_file == ["~/.ssh/one", "~/.ssh/two"]
    host.user = "bob"
    store.update("a", host)
    store.save()
    assert SshConfigStore(path).get("a").identity_file == ["~/.ssh/one", "~/.ssh/two"]
    assert path.read_text().index("Host a") < path.read_text().index("Host *")
    assert host.identity_file == ["~/.ssh/one", "~/.ssh/two"]


def test_adopt_preserves_both_identity_files(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host a\n IdentityFile ~/.ssh/one\n IdentityFile ~/.ssh/two\n")
    inc = tmp_path / "includes"
    inc.mkdir()
    (inc / "production.conf").write_text("")
    inv = HostInventory(cfg, inc)
    inv.adopt("a", "production")
    groups = {g.name: g for g in inv.groups()}
    assert (
        groups["production"].hosts[0].identity_file == groups[READONLY_GROUP].hosts[0].identity_file
    )
    assert groups["production"].hosts[0].identity_file == ["~/.ssh/one", "~/.ssh/two"]


@pytest.mark.parametrize(
    "body",
    [
        "Host other\n Include {inc}/*",
        "Match all\n Include {inc}/*.conf",
        "Host *\n HostName wrong.example\n Include {inc}/*",
        "Include {inc}/one.conf",
        "Include {inc}/prod*.conf",
        "Include /some/other/* {inc}/*",
    ],
)
def test_ineffective_includes_do_not_suppress_setup(tmp_path, body):
    cfg = tmp_path / "config"
    inc = tmp_path / "includes"
    cfg.write_text(body.format(inc=inc))
    assert not include_is_configured(cfg, inc)
    original = cfg.read_text()
    backup = add_include(cfg, inc)
    assert backup.read_text() == original
    assert include_is_configured(cfg, inc)


def test_include_with_spaces_is_valid_for_openssh(tmp_path):
    inc = tmp_path / "space directory"
    inc.mkdir()
    (inc / "a.conf").write_text("Host sample\n HostName intended.example\n")
    cfg = tmp_path / "config"
    cfg.write_text(include_line(inc) + "\nHost *\n HostName fallback.example\n")
    assert include_is_configured(cfg, inc)
    if not shutil.which("ssh"):
        pytest.skip("OpenSSH not installed")
    result = subprocess.run(
        ["ssh", "-G", "-F", str(cfg), "--", "sample"], capture_output=True, text=True, check=True
    )
    assert "hostname intended.example\n" in result.stdout


@pytest.mark.parametrize("prefix", ["Include\t", "Include=", "Include = "])
def test_include_accepts_ssh_directive_separators(tmp_path, prefix):
    inc = tmp_path / "includes"
    cfg = tmp_path / "config"
    cfg.write_text(prefix + str(inc / "*.conf") + " # comment\n")
    assert include_is_configured(cfg, inc)
