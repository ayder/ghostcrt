from pathlib import Path

import pytest

from ghostcrt.vault.vault import Vault, WrongMasterKey


def test_create_unlock_roundtrip(tmp_path: Path):
    path = tmp_path / "vault.enc"
    v = Vault.create(path, "master-key")
    v.set("db", "pw1")
    v.save()
    assert path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600

    v2 = Vault.unlock(path, "master-key")
    assert v2.get("db") == "pw1"
    assert "db" in v2.aliases()


def test_wrong_key(tmp_path: Path):
    path = tmp_path / "vault.enc"
    Vault.create(path, "right").save()
    with pytest.raises(WrongMasterKey):
        Vault.unlock(path, "wrong")


def test_delete_and_missing(tmp_path: Path):
    path = tmp_path / "vault.enc"
    v = Vault.create(path, "m")
    v.set("a", "1")
    v.delete("a")
    v.save()
    v2 = Vault.unlock(path, "m")
    assert v2.get("a") is None


def test_reset(tmp_path: Path):
    path = tmp_path / "vault.enc"
    Vault.create(path, "m").save()
    assert Vault.exists(path)
    Vault.reset(path)
    assert not Vault.exists(path)


def test_tamper_raises_wrong_key(tmp_path: Path):
    path = tmp_path / "vault.enc"
    Vault.create(path, "m").save()
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(data)
    with pytest.raises(WrongMasterKey):
        Vault.unlock(path, "m")
