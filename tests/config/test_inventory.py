from pathlib import Path

import pytest

from ghostcrt.config.inventory import READONLY_GROUP, HostInventory
from ghostcrt.config.ssh_config import SshConfigError
from ghostcrt.models import Host


def build(tmp_path: Path, ssh_config: str, groups: dict[str, str]) -> HostInventory:
    cfg = tmp_path / "config"
    cfg.write_text(ssh_config)
    inc = tmp_path / "includes"
    inc.mkdir(exist_ok=True)
    for name, body in groups.items():
        (inc / f"{name}.conf").write_text(body)
    return HostInventory(cfg, inc)


def test_each_include_file_becomes_a_group_named_after_the_file(tmp_path):
    inv = build(
        tmp_path,
        "Host bastion\n    User root\n",
        {
            "production": "Host srv1 srv2 srv3\n    User jorn\n",
            "staging": "Host srv4\n    User jornv\n",
        },
    )

    assert [g.name for g in inv.groups()] == ["production", "staging", READONLY_GROUP]


def test_readonly_group_is_pinned_last_and_not_writable(tmp_path):
    inv = build(tmp_path, "Host bastion\n", {"zzz": "Host srv1\n"})

    groups = inv.groups()

    assert groups[-1].name == READONLY_GROUP
    assert groups[-1].writable is False
    assert all(g.writable for g in groups[:-1])


def test_group_carries_its_hosts_and_patterns(tmp_path):
    inv = build(
        tmp_path,
        "",
        {"company": "Host web\n    User bob\n\nHost *.company.com\n    User jornw\n"},
    )

    group = inv.groups()[0]

    assert [h.alias for h in group.hosts] == ["web"]
    assert [p.alias for p in group.patterns] == ["*.company.com"]


def test_one_broken_group_file_does_not_hide_the_others(tmp_path, monkeypatch):
    inv = build(tmp_path, "", {"good": "Host srv1\n", "bad": "Host srv2\n"})

    from ghostcrt.config import inventory as inventory_module

    real_store = inventory_module.SshConfigStore

    class Exploding(real_store):
        def reload(self):
            if self.path.name == "bad.conf":
                raise inventory_module.SshConfigError("boom")
            super().reload()

    monkeypatch.setattr(inventory_module, "SshConfigStore", Exploding)
    inv.reload()

    by_name = {g.name: g for g in inv.groups()}
    assert by_name["bad"].error is not None
    assert [h.alias for h in by_name["good"].hosts] == ["srv1"]


def test_missing_includes_directory_yields_only_the_readonly_group(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host bastion\n")
    inv = HostInventory(cfg, tmp_path / "does-not-exist")

    assert [g.name for g in inv.groups()] == [READONLY_GROUP]


def test_hosts_flattens_every_group(tmp_path):
    inv = build(tmp_path, "Host bastion\n", {"production": "Host srv1 srv2\n"})

    assert sorted(h.alias for h in inv.hosts()) == ["bastion", "srv1", "srv2"]


def test_group_of_and_is_writable(tmp_path):
    inv = build(tmp_path, "Host bastion\n", {"production": "Host srv1\n"})

    assert inv.group_of("srv1") == "production"
    assert inv.group_of("bastion") == READONLY_GROUP
    assert inv.group_of("nope") is None
    assert inv.is_writable("srv1") is True
    assert inv.is_writable("bastion") is False


def test_group_file_shadows_the_same_alias_in_ssh_config(tmp_path):
    inv = build(
        tmp_path,
        "Host bastion\n    User bob\n",
        {"production": "Host bastion\n    User alice\n"},
    )

    by_name = {g.name: g for g in inv.groups()}

    assert by_name[READONLY_GROUP].shadowed_by == {"bastion": "production"}
    assert by_name["production"].shadowed_by == {}


def test_earlier_group_file_shadows_a_later_one(tmp_path):
    inv = build(tmp_path, "", {"aaa": "Host srv1\n", "bbb": "Host srv1\n"})

    by_name = {g.name: g for g in inv.groups()}

    assert by_name["bbb"].shadowed_by == {"srv1": "aaa"}
    assert by_name["aaa"].shadowed_by == {}


def test_unique_aliases_are_never_marked_shadowed(tmp_path):
    inv = build(tmp_path, "Host bastion\n", {"production": "Host srv1\n"})

    assert all(g.shadowed_by == {} for g in inv.groups())


def test_add_writes_into_the_named_group_file(tmp_path):
    inv = build(tmp_path, "", {"production": "Host srv1\n"})

    inv.add("production", Host(alias="srv9", hostname="10.0.0.9"))

    assert (tmp_path / "includes" / "production.conf").read_text().count("srv9") == 1
    assert inv.group_of("srv9") == "production"


def test_writing_to_the_readonly_group_is_refused(tmp_path):
    inv = build(tmp_path, "Host bastion\n", {})

    with pytest.raises(SshConfigError, match="read-only"):
        inv.add(READONLY_GROUP, Host(alias="nope"))
    with pytest.raises(SshConfigError, match="read-only"):
        inv.delete(READONLY_GROUP, "bastion")


def test_create_group_makes_an_empty_file(tmp_path):
    inv = build(tmp_path, "", {})

    inv.create_group("staging")

    assert (tmp_path / "includes" / "staging.conf").is_file()
    assert [g.name for g in inv.groups()] == ["staging", READONLY_GROUP]


def test_create_group_rejects_names_that_escape_the_directory(tmp_path):
    inv = build(tmp_path, "", {})

    for bad in ["../evil", "a/b", "..", ""]:
        with pytest.raises(SshConfigError):
            inv.create_group(bad)


def test_create_group_rejects_duplicates(tmp_path):
    inv = build(tmp_path, "", {"production": "Host srv1\n"})

    with pytest.raises(SshConfigError, match="exists"):
        inv.create_group("production")


def test_delete_group_refuses_while_it_still_has_hosts(tmp_path):
    inv = build(tmp_path, "", {"production": "Host srv1\n"})

    with pytest.raises(SshConfigError, match="not empty"):
        inv.delete_group("production")

    inv.delete_group("production", force=True)
    assert not (tmp_path / "includes" / "production.conf").exists()


def test_move_relocates_a_host_between_groups(tmp_path):
    inv = build(tmp_path, "", {"production": "Host srv1\n    User jorn\n", "staging": ""})

    inv.move("srv1", "production", "staging")

    assert inv.group_of("srv1") == "staging"
    assert "srv1" not in (tmp_path / "includes" / "production.conf").read_text()
    assert "User jorn" in (tmp_path / "includes" / "staging.conf").read_text()


def test_moving_one_alias_moves_its_whole_stanza(tmp_path):
    inv = build(
        tmp_path, "", {"production": "Host srv1 srv2 srv3\n    User jorn\n", "staging": ""}
    )

    inv.move("srv1", "production", "staging")

    assert inv.group_of("srv2") == "staging"
    assert inv.group_of("srv3") == "staging"
    assert "srv" not in (tmp_path / "includes" / "production.conf").read_text()


def test_deleting_one_alias_deletes_its_whole_stanza(tmp_path):
    inv = build(tmp_path, "", {"production": "Host srv1 srv2\n    User jorn\n"})

    inv.delete("production", "srv1")

    assert inv.group_of("srv2") is None


def test_adopt_copies_a_readonly_host_and_leaves_the_original(tmp_path):
    inv = build(tmp_path, "Host bastion\n    User bob\n", {"production": ""})

    inv.adopt("bastion", "production")

    assert "bastion" in (tmp_path / "config").read_text()
    assert "bastion" in (tmp_path / "includes" / "production.conf").read_text()
    by_name = {g.name: g for g in inv.groups()}
    assert by_name[READONLY_GROUP].shadowed_by == {"bastion": "production"}
