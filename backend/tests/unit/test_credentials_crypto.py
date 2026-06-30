import base64

import pytest

from payglue_backend.webhooks.credentials import FernetCipher


def _valid_fernet_key() -> str:
    return base64.urlsafe_b64encode(b"0" * 32).decode("ascii")


def test_fernet_cipher_round_trip() -> None:
    cipher = FernetCipher(_valid_fernet_key())

    encrypted = cipher.encrypt("super-secret")
    decrypted = cipher.decrypt(encrypted)

    assert encrypted != "super-secret"
    assert decrypted == "super-secret"


def test_fernet_cipher_rejects_invalid_key() -> None:
    with pytest.raises(ValueError):
        FernetCipher("not-a-valid-key")


def test_fernet_cipher_rejects_invalid_ciphertext() -> None:
    cipher = FernetCipher(_valid_fernet_key())

    with pytest.raises(ValueError):
        cipher.decrypt("not-a-valid-token")
