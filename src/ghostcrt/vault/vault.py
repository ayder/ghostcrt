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
VERSION = 2
SUPPORTED_VERSIONS = frozenset({1, 2})
HEADER_FMT = ">4sBIIIII"  # magic, version, time, mem, par, hash_len, salt_len
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_VAULT_BYTES = 16 * 1024 * 1024
MAX_PROFILE_ID_LEN = 64


class VaultError(Exception):
    """A vault operation failed; its message contains no secret data."""


class VaultInputError(VaultError):
    """The caller's input was rejected; nothing was read or written."""


class WrongMasterKey(VaultError):
    """Raised when vault decryption fails (wrong key, tamper, or corrupt)."""


def normalize_profile_id(raw: str) -> str | None:
    """The stored form of a profile id, or None when it breaks the rule."""
    candidate = raw.strip()
    if not 1 <= len(candidate) <= MAX_PROFILE_ID_LEN:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in candidate):
        return None
    return candidate


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


def _is_str_map(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


def _decode_payload(payload: object, version: int) -> tuple[dict[str, str], dict[str, str]]:
    """Split a decrypted payload into (profiles, hosts) for its format version.

    Format 1 is a flat {alias: password} map; it is migrated in memory, taking
    each alias verbatim as a profile id so no stored password can be lost.
    """
    if version == 1:
        if not _is_str_map(payload):
            raise WrongMasterKey("invalid vault payload")
        secrets: dict[str, str] = payload  # type: ignore[assignment]
        return dict(secrets), {alias: alias for alias in secrets}
    if not isinstance(payload, dict) or set(payload) != {"profiles", "hosts"}:
        raise WrongMasterKey("invalid vault payload")
    if not _is_str_map(payload["profiles"]) or not _is_str_map(payload["hosts"]):
        raise WrongMasterKey("invalid vault payload")
    return dict(payload["profiles"]), dict(payload["hosts"])


class Vault:
    def __init__(
        self,
        path: Path,
        key: bytes,
        profiles: dict[str, str],
        hosts: dict[str, str],
        *,
        salt: bytes,
        time_cost: int,
        memory_cost: int,
        parallelism: int,
        hash_len: int,
    ) -> None:
        self.path = path
        self._key = key
        self._profiles = profiles
        self._hosts = hosts
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
            if magic != MAGIC or version not in SUPPORTED_VERSIONS:
                raise WrongMasterKey("unsupported vault format")
            # Both supported versions have only ever written this parameter set.
            # Reject headers requesting different work before calling the
            # unauthenticated KDF.
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
            profiles, hosts = _decode_payload(json.loads(plaintext.decode("utf-8")), version)
            return cls(
                path,
                key,
                profiles,
                hosts,
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

    def profiles(self) -> list[str]:
        return sorted(self._profiles.keys())

    def get_profile(self, profile_id: str) -> str | None:
        return self._profiles.get(profile_id)

    def profile_for(self, alias: str) -> str | None:
        return self._hosts.get(alias)

    def aliases(self) -> list[str]:
        return sorted(self._hosts.keys())

    def get(self, alias: str) -> str | None:
        profile_id = self._hosts.get(alias)
        if profile_id is None:
            return None
        return self._profiles.get(profile_id)

    def update_profile(self, profile_id: str, password: str | None) -> None:
        """Create, overwrite or delete a profile, then persist.

        The id rule is checked only when creating: an id that is already a
        profile -- including one migrated verbatim from a format-1 vault -- can
        always be overwritten and deleted.
        """
        previous = (self._profiles.copy(), self._hosts.copy())
        if password is None:
            self._profiles.pop(profile_id, None)
            self._hosts = {
                alias: pid for alias, pid in self._hosts.items() if pid != profile_id
            }
        else:
            stored_id = profile_id.strip()
            if stored_id not in self._profiles:
                normalized = normalize_profile_id(profile_id)
                if normalized is None:
                    raise VaultInputError("Invalid profile id.")
                stored_id = normalized
            if not password:
                raise VaultInputError("Password cannot be empty.")
            self._profiles[stored_id] = password
        self._persist(previous)

    def update_assignment(self, alias: str, profile_id: str | None) -> None:
        """Point an alias at a profile, or remove its assignment, then persist."""
        if profile_id is not None and profile_id not in self._profiles:
            raise VaultInputError("Unknown profile.")
        previous = (self._profiles.copy(), self._hosts.copy())
        if profile_id is None:
            self._hosts.pop(alias, None)
        else:
            self._hosts[alias] = profile_id
        self._persist(previous)

    def _persist(self, previous: tuple[dict[str, str], dict[str, str]]) -> None:
        try:
            self.save()
        except VaultError:
            self._profiles, self._hosts = previous
            raise

    def save(self) -> None:
        payload = {"profiles": self._profiles, "hosts": self._hosts}
        plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
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
