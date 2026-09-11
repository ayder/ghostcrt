import struct

import pytest
from argon2.exceptions import HashingError

from ghostcrt.vault.vault import (
    HEADER_FMT,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    Vault,
    VaultError,
    WrongMasterKey,
)


@pytest.mark.parametrize(
    "field,value",
    [
        (0, 0),
        (0, 0xFFFFFFFF),
        (1, 0xFFFFFFFF),
        (2, 0xFFFFFFFF),
        (3, 16),
        (4, 0xFFFFFFFF),
    ],
)
def test_invalid_header_rejected_before_any_kdf(tmp_path, monkeypatch, field, value):
    params = [3, 65536, 4, 32, 16]
    params[field] = value
    path = tmp_path / "bad.enc"
    path.write_bytes(struct.pack(HEADER_FMT, MAGIC, VERSION, *params) + b"x" * 44)

    def forbidden(*args, **kwargs):
        pytest.fail("untrusted header reached Argon2")

    monkeypatch.setattr("ghostcrt.vault.crypto.derive_key", forbidden)
    with pytest.raises(WrongMasterKey):
        Vault.unlock(path, "synthetic-master")


def test_oversized_file_rejected_before_kdf(tmp_path, monkeypatch):
    path = tmp_path / "large.enc"
    monkeypatch.setattr("ghostcrt.vault.vault.MAX_VAULT_BYTES", HEADER_SIZE)
    path.write_bytes(b"x" * (HEADER_SIZE + 1))
    with pytest.raises(WrongMasterKey, match="large"):
        Vault.unlock(path, "synthetic-master")


def test_runtime_kdf_failure_is_a_safe_vault_error(tmp_path, monkeypatch):
    path = tmp_path / "vault.enc"
    Vault.create(path, "synthetic-master")

    def fail(*args, **kwargs):
        raise HashingError("synthetic-internal-detail")

    monkeypatch.setattr("ghostcrt.vault.crypto.derive_key", fail)
    for action in (Vault.create, Vault.unlock):
        with pytest.raises(VaultError) as exc:
            action(path, "synthetic-master")
        assert "synthetic" not in str(exc.value)


class TestSaveFailure:
    @pytest.mark.parametrize("replacement", [None, "new-password"])
    def test_failed_profile_save_restores_memory_and_disk(
        self, tmp_path, monkeypatch, replacement
    ):
        path = tmp_path / "vault.enc"
        vault = Vault.create(path, "master")
        vault.update_profile("host", "original")
        original = path.read_bytes()

        def fail(*args, **kwargs):
            raise OSError("simulated disk failure")

        monkeypatch.setattr("ghostcrt.vault.vault.os.replace", fail)
        with pytest.raises(VaultError):
            vault.update_profile("host", replacement)
        assert vault.get_profile("host") == "original"
        assert path.read_bytes() == original
        assert not list(tmp_path.glob(".vault-*"))

    @pytest.mark.parametrize("target", ["p2", None])
    def test_failed_assignment_save_restores_memory_and_disk(self, tmp_path, monkeypatch, target):
        path = tmp_path / "vault.enc"
        vault = Vault.create(path, "master")
        vault.update_profile("host", "original")
        vault.update_profile("p2", "x")
        vault.update_assignment("h", "host")
        before = path.read_bytes()

        def fail(*args, **kwargs):
            raise OSError("simulated disk failure")

        monkeypatch.setattr("ghostcrt.vault.vault.os.replace", fail)
        with pytest.raises(VaultError):
            vault.update_assignment("h", target)
        assert vault.profile_for("h") == "host"
        assert path.read_bytes() == before
        assert not list(tmp_path.glob(".vault-*"))


def test_atomic_save_does_not_change_existing_parent_permissions(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o755)
    vault = Vault.create(parent / "vault.enc", "master")
    assert parent.stat().st_mode & 0o777 == 0o755
    assert vault.path.stat().st_mode & 0o777 == 0o600
