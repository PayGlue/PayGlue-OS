# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-187: cleaning up junk/test UserProfiles kept failing with a Supabase
'admin API 405', which the fail-safe turned into 'local profile NOT deleted'.
Cause: a blank firebase_uid makes the DELETE hit .../admin/users/ (the
collection), which Supabase answers 405. A blank id (and a 405) means there is
no linked account to delete, so it must be treated as already-gone."""
from urllib import error

import pytest

from payglue_backend.tenants import supabase_admin
from payglue_backend.tenants.supabase_admin import SupabaseAdminError, delete_supabase_user


def _http_error(code: int) -> error.HTTPError:
    return error.HTTPError(url="https://x", code=code, msg="nope", hdrs=None, fp=None)


def test_blank_uid_is_a_noop_without_touching_the_network(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("no network call should happen for a blank uid")

    monkeypatch.setattr(supabase_admin.request, "urlopen", _boom)

    delete_supabase_user("")
    delete_supabase_user("   ")


def _config(settings) -> None:
    settings.SUPABASE_URL = "https://project.supabase.co"
    settings.SUPABASE_SERVICE_ROLE_KEY = "service-role-key"


def test_404_and_405_are_treated_as_already_gone(settings, monkeypatch) -> None:
    _config(settings)
    for code in (404, 405):
        def _raise(*_a, _code=code, **_k):
            raise _http_error(_code)

        monkeypatch.setattr(supabase_admin.request, "urlopen", _raise)

        # Must not raise -- nothing to delete on the Supabase side.
        delete_supabase_user("some-uid")


def test_other_errors_still_raise(settings, monkeypatch) -> None:
    _config(settings)

    def _raise(*_a, **_k):
        raise _http_error(500)

    monkeypatch.setattr(supabase_admin.request, "urlopen", _raise)

    with pytest.raises(SupabaseAdminError):
        delete_supabase_user("some-uid")
