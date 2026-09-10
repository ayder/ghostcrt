import os

import pytest

from ghostcrt.vault import crypto


def test_derive_key_length_and_determinism():
    salt = b"\x00" * crypto.DEFAULT_SALT_LEN
    k1 = crypto.derive_key("master", salt)
    k2 = crypto.derive_key("master", salt)
    assert len(k1) == 32
    assert k1 == k2
    assert crypto.derive_key("other", salt) != k1


def test_encrypt_decrypt_roundtrip():
    key = os.urandom(32)
    blob = crypto.encrypt(key, b'{"a":"b"}')
    assert crypto.decrypt(key, blob) == b'{"a":"b"}'
    assert len(blob) > 12 + 16


def test_decrypt_wrong_key_fails():
    from cryptography.exceptions import InvalidTag

    key = os.urandom(32)
    blob = crypto.encrypt(key, b"secret")
    with pytest.raises(InvalidTag):
        crypto.decrypt(os.urandom(32), blob)


def test_decrypt_tamper_fails():
    from cryptography.exceptions import InvalidTag

    key = os.urandom(32)
    blob = bytearray(crypto.encrypt(key, b"secret"))
    blob[-1] ^= 0xFF
    with pytest.raises(InvalidTag):
        crypto.decrypt(key, bytes(blob))
