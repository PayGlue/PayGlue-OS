# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import json
import logging

from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError
from django.http import HttpRequest, HttpResponse
from django.views import View

# Short timeouts everywhere: this endpoint is meant to be polled frequently by
# an external uptime monitor and must fail fast, never hang a Kuma check.
_REDIS_TIMEOUT_SECONDS = 3
_CELERY_PING_TIMEOUT_SECONDS = 3

logger = logging.getLogger(__name__)

# What a failing check says to the outside world.
#
# These endpoints exist so that an uptime monitor can ask "is the database up"
# without the database being exposed to anyone. Returning the raw exception
# defeated exactly that: a Postgres or Redis connection error carries the host,
# the address, the port and sometimes the user and database name, and it shows
# up precisely when something is broken and somebody is looking (PG-253).
#
# The real message still exists, it goes to the log where the person who can
# act on it will find it. The reader on the status page gets up or down, which
# is all a status page can honestly say anyway.
_OPAQUE_FAILURE_DETAIL = "unavailable"


def _fail(component: str, exc: object) -> tuple[bool, str]:
    """Log the real reason, hand the outside world an opaque one."""
    logger.warning("health check failed: %s: %s", component, exc)
    return False, _OPAQUE_FAILURE_DETAIL


def _check_database() -> tuple[bool, str]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, "ok"
    except OperationalError as exc:
        return _fail("database", exc)


def _check_redis() -> tuple[bool, str]:
    try:
        import redis

        client = redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
        )
        if not client.ping():
            return _fail("cache", "PING returned falsy")
        return True, "ok"
    except Exception as exc:  # redis raises its own ConnectionError/TimeoutError
        return _fail("cache", exc)


def _check_celery_worker() -> tuple[bool, str]:
    try:
        from payglue_backend.config.celery import app as celery_app

        # Inspects currently connected workers rather than queuing a task —
        # doesn't touch application data and returns immediately if no
        # worker is listening, instead of waiting on a queue that's stuck.
        replies = celery_app.control.inspect(timeout=_CELERY_PING_TIMEOUT_SECONDS).ping()
        if not replies:
            return _fail("worker", "no worker responded")
        return True, "ok"
    except Exception as exc:
        return _fail("worker", exc)


def _json_response(payload: dict[str, object], healthy: bool) -> HttpResponse:
    return HttpResponse(
        json.dumps(payload),
        status=200 if healthy else 503,
        content_type="application/json",
    )


class DatabaseHealthView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        ok, detail = _check_database()
        return _json_response({"database": "ok" if ok else "down", "detail": detail}, ok)


class CacheHealthView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        ok, detail = _check_redis()
        return _json_response({"cache": "ok" if ok else "down", "detail": detail}, ok)


class WorkerHealthView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        ok, detail = _check_celery_worker()
        return _json_response({"worker": "ok" if ok else "down", "detail": detail}, ok)


class OverallHealthView(View):
    """Single endpoint checking everything, for a one-glance dashboard status."""

    def get(self, request: HttpRequest) -> HttpResponse:
        db_ok, db_detail = _check_database()
        redis_ok, redis_detail = _check_redis()
        celery_ok, celery_detail = _check_celery_worker()
        all_ok = db_ok and redis_ok and celery_ok
        payload = {
            "status": "ok" if all_ok else "degraded",
            "database": {"status": "ok" if db_ok else "down", "detail": db_detail},
            "cache": {"status": "ok" if redis_ok else "down", "detail": redis_detail},
            "worker": {"status": "ok" if celery_ok else "down", "detail": celery_detail},
        }
        return _json_response(payload, all_ok)
