import json
import struct
from pathlib import Path

import pytest

from ghostcrt.vault import crypto
from ghostcrt.vault.vault import HEADER_FMT, HEADER_SIZE, MAGIC, Vault, WrongMasterKey


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
