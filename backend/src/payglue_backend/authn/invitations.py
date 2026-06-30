# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import hashlib


def normalize_email(email: str) -> str:
    return email.strip().lower()


def invitation_digest(decoder_key: str, email: str) -> str:
    payload = f"{decoder_key}{normalize_email(email)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def invitation_code_matches(
    *,
    decoder_key: str,
    email: str,
    provided_code: str,
    shortcode_length: int = 10,
) -> bool:
    expected = invitation_digest(decoder_key=decoder_key, email=email)
    candidate = provided_code.strip().lower()
    if not candidate:
        return False

    if len(candidate) <= shortcode_length:
        return candidate == expected[:shortcode_length]

    return candidate == expected
