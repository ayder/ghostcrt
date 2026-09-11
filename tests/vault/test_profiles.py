import json
import os
import struct
from pathlib import Path

import pytest

from ghostcrt.vault import crypto
from ghostcrt.vault.vault import (
    HEADER_FMT,
    HEADER_SIZE,
    MAGIC,
    Vault,
    VaultInputError,
    WrongMasterKey,
)


def raw_payload(path: Path, master: str) -> tuple[int, object]:
    data = path.read_bytes()
    _magic, version, time_cost, memory_cost, parallelism, hash_len, salt_len = struct.unpack(
        HEADER_FMT, data[:HEADER_SIZE]
    )
    salt_start = HEADER_SIZE
    salt_end = salt_start + salt_len
    salt = data[salt_start:salt_end]
    blob = data[salt_end:]
    key = crypto.derive_key(
        master,
        salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=hash_len,
    )
    return version, json.loads(crypto.decrypt(key, blob).decode("utf-8"))


def write_v1(path: Path, master: str, payload: dict) -> None:
    salt = os.urandom(16)
    key = crypto.derive_key(master, salt)
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        1,
        crypto.DEFAULT_TIME_COST,
        crypto.DEFAULT_MEMORY_COST,
        crypto.DEFAULT_PARALLELISM,
        crypto.DEFAULT_HASH_LEN,
        crypto.DEFAULT_SALT_LEN,
    )
    blob = crypto.encrypt(key, json.dumps(payload).encode())
    path.write_bytes(header + salt + blob)


def write_v2_raw(path: Path, master: str, obj: object) -> None:
    salt = os.urandom(16)
    key = crypto.derive_key(master, salt)
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        2,
        crypto.DEFAULT_TIME_COST,
        crypto.DEFAULT_MEMORY_COST,
        crypto.DEFAULT_PARALLELISM,
        crypto.DEFAULT_HASH_LEN,
        crypto.DEFAULT_SALT_LEN,
    )
    blob = crypto.encrypt(key, json.dumps(obj).encode())
    path.write_bytes(header + salt + blob)


class TestVaultFormat:
    def test_new_vault_writes_version_2_with_two_key_payload(self, tmp_path):
        path = tmp_path / "vault.enc"
        Vault.create(path, "synthetic-master")

        version, payload = raw_payload(path, "synthetic-master")

        assert version == 2
        assert set(payload) == {"profiles", "hosts"}

    def test_unknown_version_rejected_before_kdf(self, tmp_path, monkeypatch):
        path = tmp_path / "vault.enc"
        path.write_bytes(
            struct.pack(
                HEADER_FMT,
                MAGIC,
                3,
                crypto.DEFAULT_TIME_COST,
                crypto.DEFAULT_MEMORY_COST,
                crypto.DEFAULT_PARALLELISM,
                crypto.DEFAULT_HASH_LEN,
                crypto.DEFAULT_SALT_LEN,
            )
            + b"x" * 44
        )

        def forbidden(*args, **kwargs):
            pytest.fail("untrusted header reached Argon2")

        monkeypatch.setattr("ghostcrt.vault.crypto.derive_key", forbidden)
        with pytest.raises(WrongMasterKey, match="unsupported vault format"):
            Vault.unlock(path, "synthetic-master")

    def test_v1_file_migrates_on_unlock_verbatim(self, tmp_path):
        path = tmp_path / "vault.enc"
        long_id = "x" * 65
        write_v1(path, "synthetic-master", {"db": "pw1", long_id: "pw2"})
        before = path.read_bytes()

        v = Vault.unlock(path, "synthetic-master")

        assert v.profiles() == ["db", long_id]
        assert v.profile_for("db") == "db"
        assert v.get("db") == "pw1"
        assert v.get(long_id) == "pw2"
        assert path.read_bytes() == before

    def test_migrated_vault_saved_as_version_2_and_overlong_id_is_editable(self, tmp_path):
        path = tmp_path / "vault.enc"
        long_id = "x" * 65
        write_v1(path, "synthetic-master", {"db": "pw1", long_id: "pw2"})

        v = Vault.unlock(path, "synthetic-master")
        v.update_profile("ops", "s3")

        version, payload = raw_payload(path, "synthetic-master")
        assert version == 2
        assert payload["hosts"] == {"db": "db", long_id: long_id}
        assert len(payload["profiles"]) == 3

        v.update_profile(long_id, "new")
        assert v.get_profile(long_id) == "new"

        v.update_profile(long_id, None)
        _version, payload = raw_payload(path, "synthetic-master")
        assert payload["hosts"] == {"db": "db"}

    @pytest.mark.parametrize(
        "payload",
        [
            {"profiles": {"a": 1}, "hosts": {}},
            {"profiles": {}},
            ["x"],
            {"profiles": {}, "hosts": {"h": 2}},
            {"profiles": {}, "hosts": {}, "extra": {}},
        ],
    )
    def test_invalid_v2_payload_rejected(self, tmp_path, payload):
        path = tmp_path / "vault.enc"
        write_v2_raw(path, "synthetic-master", payload)

        with pytest.raises(WrongMasterKey, match="invalid vault payload"):
            Vault.unlock(path, "synthetic-master")


class TestVaultProfiles:
    def test_get_resolves_through_assignment(self, tmp_path):
        path = tmp_path / "vault.enc"
        v = Vault.create(path, "synthetic-master")
        v.update_profile("ops", "s3")
        v.update_assignment("web", "ops")

        assert v.get("web") == "s3"
        assert v.get("other") is None
        assert v.aliases() == ["web"]

        v2 = Vault.unlock(path, "synthetic-master")
        assert v2.get("web") == "s3"
        assert v2.get("other") is None
        assert v2.aliases() == ["web"]

        dangling_path = tmp_path / "dangling.enc"
        write_v2_raw(
            dangling_path, "synthetic-master", {"profiles": {}, "hosts": {"web": "gone"}}
        )
        v3 = Vault.unlock(dangling_path, "synthetic-master")
        assert v3.get("web") is None

    def test_profiles_sorted_and_get_profile(self, tmp_path):
        path = tmp_path / "vault.enc"
        v = Vault.create(path, "synthetic-master")
        v.update_profile("zeta", "1")
        v.update_profile("alpha", "2")

        assert v.profiles() == ["alpha", "zeta"]
        assert v.get_profile("zeta") == "1"
        assert v.get_profile("none") is None

    def test_delete_profile_unassigns_hosts(self, tmp_path):
        path = tmp_path / "vault.enc"
        v = Vault.create(path, "synthetic-master")
        v.update_profile("ops", "s3")
        v.update_assignment("web", "ops")

        v.update_profile("ops", None)

        assert v.profile_for("web") is None
        assert v.get("web") is None
        _version, payload = raw_payload(path, "synthetic-master")
        assert payload["hosts"] == {}
        assert payload["profiles"] == {}

    def test_assign_unknown_profile_raises_and_writes_nothing(self, tmp_path):
        path = tmp_path / "vault.enc"
        v = Vault.create(path, "synthetic-master")
        before = path.read_bytes()

        with pytest.raises(VaultInputError, match="Unknown profile"):
            v.update_assignment("web", "nope")

        assert v.profile_for("web") is None
        assert path.read_bytes() == before

    @pytest.mark.parametrize("profile_id", ["", " ", "a\x01", "x" * 65])
    def test_invalid_id_on_creation_and_empty_password_rejected(self, tmp_path, profile_id):
        path = tmp_path / "vault.enc"
        v = Vault.create(path, "synthetic-master")

        with pytest.raises(VaultInputError, match="Invalid profile id"):
            v.update_profile(profile_id, "p")
        assert v.profiles() == []

        with pytest.raises(VaultInputError, match="Password cannot be empty"):
            v.update_profile("a", "")

        v.update_profile("  ops  ", "p")
        assert v.profiles() == ["ops"]

    def test_no_op_assignment_and_delete_still_save(self, tmp_path):
        path = tmp_path / "vault.enc"
        v = Vault.create(path, "synthetic-master")

        before = path.read_bytes()
        v.update_assignment("web", None)
        assert v.aliases() == []
        after = path.read_bytes()
        assert after != before

        before = after
        v.update_profile("ghost", None)
        assert v.profiles() == []
        after = path.read_bytes()
        assert after != before
