# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_health_db_reports_ok_against_real_test_database() -> None:
    client = Client()
    response = client.get("/health/db")

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body == {"database": "ok", "detail": "ok"}


def test_health_cache_reports_ok_when_redis_reachable() -> None:
    client = Client()
    fake_redis = MagicMock()
    fake_redis.ping.return_value = True

    with patch("redis.from_url", return_value=fake_redis):
        response = client.get("/health/cache")

    assert response.status_code == 200
    assert json.loads(response.content) == {"cache": "ok", "detail": "ok"}


def test_health_cache_returns_503_when_redis_unreachable() -> None:
    client = Client()

    with patch("redis.from_url", side_effect=ConnectionError("refused")):
        response = client.get("/health/cache")

    assert response.status_code == 503
    body = json.loads(response.content)
    assert body["cache"] == "down"
    # Not "refused". The endpoint is public so an uptime monitor can reach it,
    # and a Redis connection error names the host and port it failed to reach
    # (PG-253). The real message goes to the log instead, see the next test.
    assert body["detail"] == "unavailable"


def test_health_worker_reports_ok_when_a_worker_responds() -> None:
    client = Client()
    fake_inspect = MagicMock()
    fake_inspect.ping.return_value = {"celery@worker-1": {"ok": "pong"}}

    with patch("payglue_backend.config.celery.app.control.inspect", return_value=fake_inspect):
        response = client.get("/health/worker")

    assert response.status_code == 200
    assert json.loads(response.content) == {"worker": "ok", "detail": "ok"}


def test_health_worker_returns_503_when_no_worker_responds() -> None:
    client = Client()
    fake_inspect = MagicMock()
    fake_inspect.ping.return_value = None

    with patch("payglue_backend.config.celery.app.control.inspect", return_value=fake_inspect):
        response = client.get("/health/worker")

    assert response.status_code == 503
    assert json.loads(response.content) == {"worker": "down", "detail": "unavailable"}


def test_health_overall_returns_503_when_any_component_is_down() -> None:
    client = Client()

    with patch("redis.from_url", side_effect=ConnectionError("refused")):
        response = client.get("/health")

    assert response.status_code == 503
    body = json.loads(response.content)
    assert body["status"] == "degraded"
    assert body["database"]["status"] == "ok"
    assert body["cache"]["status"] == "down"


def test_health_overall_returns_200_when_everything_is_up() -> None:
    client = Client()
    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    fake_inspect = MagicMock()
    fake_inspect.ping.return_value = {"celery@worker-1": {"ok": "pong"}}

    with patch("redis.from_url", return_value=fake_redis), patch(
        "payglue_backend.config.celery.app.control.inspect", return_value=fake_inspect
    ):
        response = client.get("/health")

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert body["cache"]["status"] == "ok"
    assert body["worker"]["status"] == "ok"


def test_failure_detail_never_reaches_the_caller_but_does_reach_the_log(caplog) -> None:
    """The whole point of these endpoints: report the state, not the topology.

    A Redis error message contains the address it tried to reach. That is the
    one thing a public health endpoint must not hand out, and the one thing the
    person on call actually needs, so it goes to the log instead.
    """
    client = Client()
    secret_ish = "connection refused to redis-internal.example:6379"

    with caplog.at_level("WARNING"):
        with patch("redis.from_url", side_effect=ConnectionError(secret_ish)):
            response = client.get("/health/cache")

    assert secret_ish not in response.content.decode()
    assert secret_ish in caplog.text


def test_overall_health_hides_the_detail_of_every_component(caplog) -> None:
    client = Client()

    with caplog.at_level("WARNING"):
        with patch("redis.from_url", side_effect=ConnectionError("redis-internal.example:6379")):
            response = client.get("/health")

    body = json.loads(response.content)
    assert body["cache"] == {"status": "down", "detail": "unavailable"}
    assert "redis-internal.example" not in response.content.decode()
