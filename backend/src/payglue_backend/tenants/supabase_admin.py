# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Supabase Admin API calls for keeping PayGlue's UserProfile in sync with
the underlying Supabase Auth account it's tied to.
"""
import json
from urllib import error, request

from django.conf import settings

_HEADERS = {"User-Agent": "PayGlue/1.0 (https://payglue.io)"}


class SupabaseAdminError(Exception):
    pass


def _require_config() -> None:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise SupabaseAdminError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY is not configured."
        )


def _request_admin(method: str, path: str, body: dict | None = None) -> dict:
    _require_config()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(
        url=f"{settings.SUPABASE_URL}{path}",
        data=data,
        headers={
            **_HEADERS,
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        raise SupabaseAdminError(f"Supabase admin API {exc.code}: {body_text}") from exc


def _post_admin(path: str, body: dict) -> dict:
    return _request_admin("POST", path, body)


def get_supabase_user_by_email(email: str) -> str | None:
    """Looks up an existing Supabase Auth user id by email, or None."""
    from urllib.parse import quote

    result = _request_admin("GET", f"/auth/v1/admin/users?email={quote(email)}")
    users = result.get("users", [])
    for user in users:
        if user.get("email", "").lower() == email.lower():
            return user["id"]
    return None


def update_supabase_user_password(supabase_user_id: str, password: str) -> None:
    """Resets the password for an existing Supabase Auth user."""
    _request_admin(
        "PUT", f"/auth/v1/admin/users/{supabase_user_id}", {"password": password}
    )


def delete_supabase_user(supabase_user_id: str) -> None:
    """Deletes the Supabase Auth account for the given user id.

    A 404 (already gone) is treated as success, since the end state we
    care about — the account no longer exists — is already true.

    A blank id means the profile was never linked to a real Supabase account
    (some old/test rows have an empty firebase_uid). There is nothing to delete
    there, and hitting the endpoint anyway would send DELETE to the collection
    URL (.../admin/users/), which Supabase answers with 405 Method Not Allowed
    -- the exact error that was blocking cleanup of those rows. Treat both the
    blank id and a 405 as already-gone so the local profile delete can proceed.
    """
    if not supabase_user_id or not supabase_user_id.strip():
        return
    _require_config()
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{supabase_user_id}"
    req = request.Request(
        url=url,
        headers={
            **_HEADERS,
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        },
        method="DELETE",
    )
    try:
        request.urlopen(req, timeout=8)
    except error.HTTPError as exc:
        if exc.code in (404, 405):
            return
        body = exc.read().decode("utf-8") if exc.fp else ""
        raise SupabaseAdminError(f"Supabase admin API {exc.code}: {body}") from exc


def create_supabase_user(email: str, password: str) -> str:
    """Creates an auto-confirmed Supabase Auth user with the given password.

    For development/testing accounts where André signs in with a password
    he chose himself, rather than a magic link. Returns the new user's id.
    """
    body = {"email": email, "password": password, "email_confirm": True}
    return _post_admin("/auth/v1/admin/users", body)["id"]


def invite_supabase_user(email: str) -> str:
    """Creates a Supabase Auth user and sends them an invite/magic-link
    email via Supabase's own configured mail settings (independent of
    PayGlue's own transactional email setup). Returns the new user's id.
    """
    return _post_admin("/auth/v1/invite", {"email": email})["id"]
