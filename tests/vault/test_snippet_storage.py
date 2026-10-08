import json
import os
import struct
from pathlib import Path

import pytest

from ghostcrt.vault import crypto
from ghostcrt.vault.snippets import Snippet
from ghostcrt.vault.vault import (
    HEADER_FMT,
    HEADER_SIZE,
    MAGIC,
    Vault,
    VaultError,
    VaultInputError,
    WrongMasterKey,
)

MASTER = "synthetic-master"


def read_raw(path: Path) -> tuple[int, dict]:
    data = path.read_bytes()
    _magic, version, time_cost, memory_cost, parallelism, hash_len, salt_len = struct.unpack(
        HEADER_FMT, data[:HEADER_SIZE]
    )
    salt = data[HEADER_SIZE : HEADER_SIZE + salt_len]
    key = crypto.derive_key(
        MASTER,
        salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=hash_len,
    )
    blob = data[HEADER_SIZE + salt_len :]
    return version, json.loads(crypto.decrypt(key, blob).decode("utf-8"))


def write_raw(path: Path, version: int, payload: object) -> None:
    salt = os.urandom(crypto.DEFAULT_SALT_LEN)
    key = crypto.derive_key(MASTER, salt)
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        version,
        crypto.DEFAULT_TIME_COST,
        crypto.DEFAULT_MEMORY_COST,
        crypto.DEFAULT_PARALLELISM,
        crypto.DEFAULT_HASH_LEN,
        crypto.DEFAULT_SALT_LEN,
    )
    path.write_bytes(header + salt + crypto.encrypt(key, json.dumps(payload).encode()))


def test_new_vault_is_format_3_with_no_snippets(tmp_path):
    path = tmp_path / "vault.enc"
    vault = Vault.create(path, MASTER)

    version, payload = read_raw(path)

    assert version == 3
    assert payload == {"profiles": {}, "hosts": {}, "snippets": {}}
    assert vault.snippets() == []


def test_snippets_round_trip_in_slot_order(tmp_path):
    path = tmp_path / "vault.enc"
    vault = Vault.create(path, MASTER)
    vault.update_snippet(3, "logs", "tail -f /var/log/syslog\\n")
    vault.update_snippet(1, "  sudo  ", "synthetic-pw\\n")

    reread = Vault.unlock(path, MASTER)

    assert reread.snippets() == [
        Snippet(1, "sudo", "synthetic-pw\\n"),
        Snippet(3, "logs", "tail -f /var/log/syslog\\n"),
    ]
    assert reread.get_snippet(2) is None
    assert read_raw(path)[1]["snippets"] == {
        "1": {"name": "sudo", "text": "synthetic-pw\\n"},
        "3": {"name": "logs", "text": "tail -f /var/log/syslog\\n"},
    }


def test_format_2_opens_without_snippets_and_migrates_on_first_change(tmp_path):
    path = tmp_path / "vault.enc"
    write_raw(path, 2, {"profiles": {"ops": "s3"}, "hosts": {"db": "ops"}})
    before = path.read_bytes()

    vault = Vault.unlock(path, MASTER)

    assert vault.snippets() == []
    assert path.read_bytes() == before

    vault.update_snippet(1, "sudo", "pw")

    version, payload = read_raw(path)
    assert version == 3
    assert payload["profiles"] == {"ops": "s3"}
    assert payload["hosts"] == {"db": "ops"}
    assert payload["snippets"] == {"1": {"name": "sudo", "text": "pw"}}


@pytest.mark.parametrize(
    ("version", "payload"),
    [
        (3, {"profiles": {}, "hosts": {}}),
        (2, {"profiles": {}, "hosts": {}, "snippets": {}}),
        (3, {"profiles": {}, "hosts": {}, "snippets": []}),
        (3, {"profiles": {}, "hosts": {}, "snippets": {"0": {"name": "a", "text": "b"}}}),
        (3, {"profiles": {}, "hosts": {}, "snippets": {"6": {"name": "a", "text": "b"}}}),
        (3, {"profiles": {}, "hosts": {}, "snippets": {"1": {"name": "a"}}}),
        (3, {"profiles": {}, "hosts": {}, "snippets": {"1": {"name": "a", "text": "b", "x": "c"}}}),
        (3, {"profiles": {}, "hosts": {}, "snippets": {"1": {"name": 1, "text": "b"}}}),
        (3, {"profiles": {}, "hosts": {}, "snippets": {"1": "b"}}),
    ],
)
def test_malformed_snippet_payload_is_rejected(tmp_path, version, payload):
    path = tmp_path / "vault.enc"
    write_raw(path, version, payload)

    with pytest.raises(WrongMasterKey, match="invalid vault payload"):
        Vault.unlock(path, MASTER)


@pytest.mark.parametrize(
    ("slot", "name", "text", "message"),
    [
        (0, "a", "b", "Invalid snippet slot."),
        (6, "a", "b", "Invalid snippet slot."),
        ("1", "a", "b", "Invalid snippet slot."),
        (1, "", "b", "Invalid snippet name."),
        (1, "x" * 17, "b", "Invalid snippet name."),
        (1, "a\x01", "b", "Invalid snippet name."),
        (1, "a", "", "Text cannot be empty."),
        (1, "a", "x" * 4097, "Text is longer than 4096 characters."),
        (1, "a", "a\x07", "Text contains control characters."),
    ],
)
def test_invalid_snippet_is_rejected_and_nothing_is_written(tmp_path, slot, name, text, message):
    path = tmp_path / "vault.enc"
    vault = Vault.create(path, MASTER)
    before = path.read_bytes()

    with pytest.raises(VaultInputError, match=message):
        vault.update_snippet(slot, name, text)

    assert path.read_bytes() == before
    assert vault.snippets() == []


def test_delete_removes_the_slot(tmp_path):
    path = tmp_path / "vault.enc"
    vault = Vault.create(path, MASTER)
    vault.update_snippet(2, "logs", "tail\\n")

    vault.update_snippet(2, "logs", None)

    assert vault.get_snippet(2) is None
    assert Vault.unlock(path, MASTER).snippets() == []


def test_failed_save_restores_previous_snippets(tmp_path, monkeypatch):
    path = tmp_path / "vault.enc"
    vault = Vault.create(path, MASTER)
    vault.update_snippet(1, "sudo", "old")

    def disk_full(*args, **kwargs):
        raise OSError("synthetic disk full")

    monkeypatch.setattr("ghostcrt.vault.vault._atomic_write", disk_full)

    with pytest.raises(VaultError):
        vault.update_snippet(1, "sudo", "new")
    with pytest.raises(VaultError):
        vault.update_snippet(2, "logs", "tail")

    assert vault.snippets() == [Snippet(1, "sudo", "old")]


def test_vault_repr_never_shows_snippet_text(tmp_path):
    vault = Vault.create(tmp_path / "vault.enc", MASTER)
    vault.update_snippet(1, "sudo", "synthetic-secret")

    assert "synthetic-secret" not in repr(vault)
