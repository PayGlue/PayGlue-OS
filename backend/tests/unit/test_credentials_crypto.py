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


def _other_fernet_key() -> str:
    return base64.urlsafe_b64encode(b"1" * 32).decode("ascii")


def test_previous_key_still_decrypts_and_new_values_use_the_current_key() -> None:
    old = FernetCipher(_valid_fernet_key(), previous_keys=[])
    stored = old.encrypt("ghost-admin-key")

    cipher = FernetCipher(_other_fernet_key(), previous_keys=[_valid_fernet_key()])

    assert cipher.decrypt(stored) == "ghost-admin-key"
    assert not cipher.is_current(stored)
    fresh = cipher.encrypt("new-value")
    assert cipher.is_current(fresh)
    with pytest.raises(ValueError):
        old.decrypt(fresh)


def test_rotate_moves_a_value_to_the_current_key() -> None:
    stored = FernetCipher(_valid_fernet_key(), previous_keys=[]).encrypt("secret")
    cipher = FernetCipher(_other_fernet_key(), previous_keys=[_valid_fernet_key()])

    rotated = cipher.rotate(stored)

    assert cipher.is_current(rotated)
    assert FernetCipher(_other_fernet_key(), previous_keys=[]).decrypt(rotated) == "secret"


def test_without_the_previous_key_old_values_are_unreadable() -> None:
    stored = FernetCipher(_valid_fernet_key(), previous_keys=[]).encrypt("secret")

    with pytest.raises(ValueError):
        FernetCipher(_other_fernet_key(), previous_keys=[]).decrypt(stored)


def test_invalid_previous_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="CREDENTIAL_ENCRYPTION_KEY_PREVIOUS"):
        FernetCipher(_valid_fernet_key(), previous_keys=["not-a-valid-key"])
