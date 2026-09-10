from __future__ import annotations

import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_TIME_COST = 3
DEFAULT_MEMORY_COST = 65536  # KiB = 64 MiB
DEFAULT_PARALLELISM = 4
DEFAULT_HASH_LEN = 32
DEFAULT_SALT_LEN = 16
NONCE_LEN = 12


def derive_key(
    password: str,
    salt: bytes,
    *,
    time_cost: int = DEFAULT_TIME_COST,
    memory_cost: int = DEFAULT_MEMORY_COST,
    parallelism: int = DEFAULT_PARALLELISM,
    hash_len: int = DEFAULT_HASH_LEN,
) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=hash_len,
        type=Type.ID,
    )


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt(key: bytes, blob: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    if len(blob) < NONCE_LEN + 16:
        raise ValueError("ciphertext too short")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, None)
