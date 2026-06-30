from dataclasses import dataclass
import base64
import hashlib
import hmac
from datetime import UTC, datetime

import pytest

from payglue_backend.core.errors import MissingCredentialsError
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.polar import PolarPaymentAdapter
from payglue_backend.webhooks.credentials import FernetCipher
from payglue_backend.webhooks.credentials import FirestoreCredentialProvider


def _valid_fernet_key() -> str:
    return base64.urlsafe_b64encode(b"1" * 32).decode("ascii")


@dataclass
class _FakeSnapshot:
    payload: dict[str, object] | None

    @property
    def exists(self) -> bool:
        return self.payload is not None

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload or {})


class _FakeDocument:
    def __init__(self, path: str, state: dict[str, dict[str, object]]) -> None:
        self.path = path
        self._state = state

    def get(self) -> _FakeSnapshot:
        return _FakeSnapshot(self._state.get(self.path))

    def set(self, payload: dict[str, object], merge: bool = False) -> None:
        if merge and self.path in self._state:
            updated = dict(self._state[self.path])
            updated.update(payload)
            self._state[self.path] = updated
            return
        self._state[self.path] = dict(payload)


class _FakeCollection:
    def __init__(self, prefix: str, state: dict[str, dict[str, object]]) -> None:
        self._prefix = prefix
        self._state = state

    def document(self, key: str) -> _FakeDocument:
        return _FakeDocument(f"{self._prefix}/{key}", self._state)


class _FakeFirestoreClient:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, object]] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(name, self.state)


def test_firestore_provider_set_and_get_credentials_round_trip() -> None:
    client = _FakeFirestoreClient()
    provider = FirestoreCredentialProvider(
        client=client,
        cipher=FernetCipher(_valid_fernet_key()),
        collection_name="integration_credentials",
    )

    metadata = provider.set_credentials(
        tenant_ctx=TenantContext(tenant_slug="tenant-a"),
        provider_key="polar",
        credentials={"webhook_secret": "secret-value"},
    )

    fetched = provider.get_credentials(
        tenant_ctx=TenantContext(tenant_slug="tenant-a"),
        provider_key="polar",
    )

    assert fetched == {"webhook_secret": "secret-value"}
    assert metadata["backend"] == "firestore"
    assert metadata["document_path"] == "integration_credentials/tenant-a--polar"
    assert metadata["masked_keys"] == ["webhook_secret"]
    stored_payload = client.state["integration_credentials/tenant-a--polar"]
    assert stored_payload["credentials"] != {"webhook_secret": "secret-value"}


def test_firestore_provider_raises_when_credentials_missing() -> None:
    provider = FirestoreCredentialProvider(
        client=_FakeFirestoreClient(),
        cipher=FernetCipher(_valid_fernet_key()),
    )

    with pytest.raises(MissingCredentialsError):
        provider.get_credentials(TenantContext(tenant_slug="tenant-a"), "polar")


def test_firestore_provider_raises_on_invalid_ciphertext() -> None:
    client = _FakeFirestoreClient()
    client.state["tenant_provider_credentials/tenant-a--polar"] = {
        "tenant_slug": "tenant-a",
        "provider_key": "polar",
        "credentials": {"webhook_secret": "invalid-token"},
    }
    provider = FirestoreCredentialProvider(
        client=client,
        cipher=FernetCipher(_valid_fernet_key()),
    )

    with pytest.raises(MissingCredentialsError):
        provider.get_credentials(TenantContext(tenant_slug="tenant-a"), "polar")


def test_polar_adapter_fetches_credentials_via_firestore_provider() -> None:
    client = _FakeFirestoreClient()
    provider = FirestoreCredentialProvider(
        client=client,
        cipher=FernetCipher(_valid_fernet_key()),
    )
    provider.set_credentials(
        tenant_ctx=TenantContext(tenant_slug="tenant-a"),
        provider_key="polar",
        credentials={"webhook_secret": "test-secret"},
    )

    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    adapter = PolarPaymentAdapter(
        credential_provider=provider,
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )

    digest = hmac.new(
        b"test-secret", str(timestamp).encode("utf-8") + b"." + body, hashlib.sha256
    ).hexdigest()
    adapter.verify_webhook(
        body,
        {"Polar-Signature": f"t={timestamp},v1={digest}"},
        TenantContext(tenant_slug="tenant-a"),
    )
