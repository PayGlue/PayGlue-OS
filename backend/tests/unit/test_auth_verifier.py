import pytest

from payglue_backend.authn.verifier import (
    AuthVerificationUnavailableError,
    _decode_with_firebase,
)


class _AuthRaisingValueError:
    def verify_id_token(self, token: str, check_revoked: bool) -> dict[str, object]:
        del token, check_revoked
        raise ValueError("sdk misconfigured")


def test_decode_with_firebase_maps_value_error_to_unavailable() -> None:
    with pytest.raises(AuthVerificationUnavailableError):
        _decode_with_firebase(_AuthRaisingValueError(), "token")
