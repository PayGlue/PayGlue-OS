# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md


def normalize_email(email: str) -> str:
    return email.strip().lower()
