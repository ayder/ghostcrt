from pathlib import Path

from ghostcrt.config.ssh_config import SshConfigStore, is_concrete_alias
from ghostcrt.models import Host

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ssh_config"


def test_is_concrete():
    assert is_concrete_alias("db")
    assert not is_concrete_alias("*")
    assert not is_concrete_alias("*.prod")
    assert not is_concrete_alias("!exclude")


def test_hosts_concrete_only_expands_multi(tmp_path: Path):
    cfg = tmp_path / "config"
    cfg.write_text(FIXTURE.read_text())
    store = SshConfigStore(cfg)
    aliases = [h.alias for h in store.hosts()]
    assert "db" in aliases
    assert "primary-db" in aliases
    assert "web" in aliases
    assert "*" not in aliases
    assert "*.prod" not in aliases
    db = store.get("primary-db")
    assert db is not None
    assert db.hostname == "10.0.0.5"
    assert set(db.aliases) == {"db", "primary-db"}


def test_add_update_delete_roundtrip(tmp_path: Path):
    cfg = tmp_path / "config"
    cfg.write_text("Host a\n    HostName 1.2.3.4\n")
    store = SshConfigStore(cfg)
    store.add(Host(alias="b", hostname="5.6.7.8", user="u"))
    store.save()
    store2 = SshConfigStore(cfg)
    assert store2.get("b") is not None
    store2.update("b", Host(alias="b", hostname="9.9.9.9", user="u"))
    store2.save()
    assert SshConfigStore(cfg).get("b").hostname == "9.9.9.9"
    store3 = SshConfigStore(cfg)
    store3.delete("b")
    store3.save()
    assert SshConfigStore(cfg).get("b") is None
    assert SshConfigStore(cfg).get("a") is not None


def test_delete_multi_alias_removes_whole_block(tmp_path: Path):
    cfg = tmp_path / "config"
    cfg.write_text(FIXTURE.read_text())
    store = SshConfigStore(cfg)
    store.delete("primary-db")
    store.save()
    s2 = SshConfigStore(cfg)
    assert s2.get("db") is None
    assert s2.get("primary-db") is None
    assert s2.get("web") is not None


def test_patterns_returns_wildcard_stanzas(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host srv1 srv2\n    User jorn\n\nHost *.company.com\n    User jornw\n")
    store = SshConfigStore(cfg)

    patterns = store.patterns()

    assert [p.alias for p in patterns] == ["*.company.com"]
    assert patterns[0].user == "jornw"


def test_patterns_are_not_listed_as_hosts(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host *.company.com\n    User jornw\n")
    store = SshConfigStore(cfg)

    assert store.hosts() == []


def test_mixed_stanza_splits_into_host_and_pattern(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host web *.example.com\n    User bob\n")
    store = SshConfigStore(cfg)

    assert [h.alias for h in store.hosts()] == ["web"]
    assert [p.alias for p in store.patterns()] == ["*.example.com"]


def test_gcp_iap_options_roundtrip(tmp_path: Path):
    cfg = tmp_path / "config"
    store = SshConfigStore(cfg)
    proxy_command = (
        "gcloud compute start-iap-tunnel %h %p --listen-on-stdin "
        "--project=my-project --zone=europe-west1-b"
    )
    store.add(
        Host(
            alias="gcp-vm",
            hostname="actual-vm-name",
            user="gcp-user",
            identity_file="~/.ssh/google_compute_engine",
            extra={
                "proxycommand": proxy_command,
                "identitiesonly": "yes",
                "userknownhostsfile": "~/.ssh/google_compute_known_hosts",
                "controlmaster": "auto",
                "controlpath": "~/.ssh/sockets/%r@%h:%p",
                "controlpersist": "10m",
            },
        )
    )

    store.save()

    saved = cfg.read_text()
    assert f"ProxyCommand {proxy_command}" in saved
    assert "IdentitiesOnly yes" in saved
    assert "UserKnownHostsFile ~/.ssh/google_compute_known_hosts" in saved
    assert "ControlMaster auto" in saved
    loaded = SshConfigStore(cfg).get("gcp-vm")
    assert loaded is not None
    assert loaded.extra["proxycommand"] == proxy_command
    assert loaded.extra["controlpersist"] == "10m"


def test_repeated_forwarding_directives_roundtrip(tmp_path: Path):
    cfg = tmp_path / "config"
    store = SshConfigStore(cfg)
    store.add(
        Host(
            alias="tunnels",
            extra={
                "localforward": ["8080 localhost:80", "5432 database.internal:5432"],
                "remoteforward": "9000 localhost:9000",
                "dynamicforward": "1080",
            },
        )
    )

    store.save()

    loaded = SshConfigStore(cfg).get("tunnels")
    assert loaded is not None
    assert loaded.extra["localforward"] == [
        "8080 localhost:80",
        "5432 database.internal:5432",
    ]
    assert loaded.extra["remoteforward"] == "9000 localhost:9000"
    assert cfg.read_text().count("LocalForward") == 2
