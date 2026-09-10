from __future__ import annotations

import json
import os
import struct
import tempfile
from pathlib import Path

from argon2.exceptions import HashingError
from cryptography.exceptions import InvalidTag

from ghostcrt.vault import crypto

MAGIC = b"PSM1"
VERSION = 1
HEADER_FMT = ">4sBIIIII"  # magic, version, time, mem, par, hash_len, salt_len
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_VAULT_BYTES = 16 * 1024 * 1024


class VaultError(Exception):
    """A vault operation failed; its message contains no secret data."""


class WrongMasterKey(VaultError):
    """Raised when vault decryption fails (wrong key, tamper, or corrupt)."""


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Do not chmod an arbitrary existing parent supplied through --vault.
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".vault-", delete=False) as f:
            tmp = Path(f.name)
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class Vault:
    def __init__(
        self,
        path: Path,
        key: bytes,
        secrets: dict[str, str],
        *,
        salt: bytes,
        time_cost: int,
        memory_cost: int,
        parallelism: int,
        hash_len: int,
    ) -> None:
        self.path = path
        self._key = key
        self._secrets = secrets
        self._salt = salt
        self._time_cost = time_cost
        self._memory_cost = memory_cost
        self._parallelism = parallelism
        self._hash_len = hash_len

    def __repr__(self) -> str:
        return f"Vault(path={self.path!r}, aliases={self.aliases()!r})"

    @staticmethod
    def exists(path: Path) -> bool:
        return path.is_file()

    @classmethod
    def create(cls, path: Path, master_password: str) -> Vault:
        salt = os.urandom(crypto.DEFAULT_SALT_LEN)
        try:
            key = crypto.derive_key(master_password, salt)
        except HashingError as exc:
            raise VaultError("Unable to derive the vault key.") from exc
        vault = cls(
            path,
            key,
            {},
            salt=salt,
            time_cost=crypto.DEFAULT_TIME_COST,
            memory_cost=crypto.DEFAULT_MEMORY_COST,
            parallelism=crypto.DEFAULT_PARALLELISM,
            hash_len=crypto.DEFAULT_HASH_LEN,
        )
        vault.save()
        return vault

    @classmethod
    def unlock(cls, path: Path, master_password: str) -> Vault:
        try:
            with path.open("rb") as f:
                data = f.read(MAX_VAULT_BYTES + 1)
            if len(data) > MAX_VAULT_BYTES:
                raise WrongMasterKey("vault is too large")
            if len(data) < HEADER_SIZE:
                raise WrongMasterKey("vault header too short")
            magic, version, time_cost, memory_cost, parallelism, hash_len, salt_len = struct.unpack(
                HEADER_FMT, data[:HEADER_SIZE]
            )
            if magic != MAGIC or version != VERSION:
                raise WrongMasterKey("unsupported vault format")
            # Version 1 has only ever written this parameter set. Reject headers
            # requesting different work before calling the unauthenticated KDF.
            if (time_cost, memory_cost, parallelism, hash_len, salt_len) != (
                crypto.DEFAULT_TIME_COST,
                crypto.DEFAULT_MEMORY_COST,
                crypto.DEFAULT_PARALLELISM,
                crypto.DEFAULT_HASH_LEN,
                crypto.DEFAULT_SALT_LEN,
            ):
                raise WrongMasterKey("unsupported vault parameters")
            salt_start = HEADER_SIZE
            salt_end = salt_start + salt_len
            if len(data) < salt_end + crypto.NONCE_LEN + 16:
                raise WrongMasterKey("vault truncated")
            salt = data[salt_start:salt_end]
            blob = data[salt_end:]
            key = crypto.derive_key(
                master_password,
                salt,
                time_cost=time_cost,
                memory_cost=memory_cost,
                parallelism=parallelism,
                hash_len=hash_len,
            )
            try:
                plaintext = crypto.decrypt(key, blob)
            except (InvalidTag, ValueError) as exc:
                raise WrongMasterKey("wrong master key or corrupt vault") from exc
            secrets = json.loads(plaintext.decode("utf-8"))
            if not isinstance(secrets, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in secrets.items()
            ):
                raise WrongMasterKey("invalid vault payload")
            return cls(
                path,
                key,
                secrets,
                salt=salt,
                time_cost=time_cost,
                memory_cost=memory_cost,
                parallelism=parallelism,
                hash_len=hash_len,
            )
        except WrongMasterKey:
            raise
        except OSError as exc:
            raise VaultError("Unable to read vault.") from exc
        except HashingError as exc:
            raise VaultError("Unable to derive the vault key.") from exc
        except (struct.error, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WrongMasterKey("corrupt vault") from exc

    @staticmethod
    def reset(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise VaultError("Unable to reset vault.") from exc

    def get(self, alias: str) -> str | None:
        return self._secrets.get(alias)

    def set(self, alias: str, password: str) -> None:
        self._secrets[alias] = password

    def delete(self, alias: str) -> None:
        self._secrets.pop(alias, None)

    def aliases(self) -> list[str]:
        return sorted(self._secrets.keys())

    def update_password(self, alias: str, password: str | None) -> None:
        """Persist a change, restoring the previous state if saving fails."""
        previous = self._secrets.copy()
        if password is None:
            self.delete(alias)
        else:
            self.set(alias, password)
        try:
            self.save()
        except VaultError:
            self._secrets = previous
            raise

    def save(self) -> None:
        plaintext = json.dumps(self._secrets, separators=(",", ":"), sort_keys=True).encode("utf-8")
        blob = crypto.encrypt(self._key, plaintext)
        header = struct.pack(
            HEADER_FMT,
            MAGIC,
            VERSION,
            self._time_cost,
            self._memory_cost,
            self._parallelism,
            self._hash_len,
            len(self._salt),
        )
        data = header + self._salt + blob
        if len(data) > MAX_VAULT_BYTES:
            raise VaultError("Vault is too large to save.")
        try:
            _atomic_write(self.path, data, mode=0o600)
        except OSError as exc:
            raise VaultError("Unable to save vault. Check disk space and permissions.") from exc
