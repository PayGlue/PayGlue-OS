# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

from payglue_backend.core.errors import MissingCredentialsError
from payglue_backend.core.models import TenantContext


class FernetCipher:
    def __init__(self, key: str | None = None) -> None:
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as exc:  # pragma: no cover - depends on runtime install
            raise RuntimeError(
                "cryptography package is required for encrypted credentials"
            ) from exc

        self._invalid_token_type = InvalidToken
        resolved_key = key or getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "")
        if not isinstance(resolved_key, str) or not resolved_key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be configured")
        # Fernet requires exact base64 padding; add it if missing
        padded_key = resolved_key + "=" * (-len(resolved_key) % 4)
        try:
            self._fernet = Fernet(padded_key.encode("utf-8"))
        except Exception as exc:
            raise ValueError("Invalid CREDENTIAL_ENCRYPTION_KEY") from exc

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode("utf-8"))
        except self._invalid_token_type as exc:
            raise ValueError("Invalid encrypted credential value") from exc
        return decrypted.decode("utf-8")


class EnvCredentialProvider:
    def __init__(self, config: Mapping[str, object] | None = None) -> None:
        self._config = (
            config
            if config is not None
            else getattr(settings, "PROVIDER_CREDENTIALS", {})
        )
        self._allow_wildcard = getattr(
            settings, "PROVIDER_CREDENTIALS_ALLOW_WILDCARD", False
        )

    @staticmethod
    def _metadata(
        tenant_slug: str,
        provider_key: str,
        credentials: Mapping[str, str],
    ) -> dict[str, object]:
        return {
            "backend": "env",
            "document_path": f"env://{tenant_slug}/{provider_key}",
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "masked_keys": sorted(credentials.keys()),
        }

    def set_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
        credentials: Mapping[str, str],
    ) -> Mapping[str, object]:
        tenant_config = self._config.get(tenant_ctx.tenant_slug)
        if not isinstance(tenant_config, dict):
            tenant_config = {}
            if isinstance(self._config, dict):
                self._config[tenant_ctx.tenant_slug] = tenant_config

        filtered: dict[str, str] = {
            key: value
            for key, value in credentials.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
        if not filtered:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=provider_key,
                missing_fields=("provider credentials",),
            )

        tenant_config[provider_key] = filtered
        return self._metadata(tenant_ctx.tenant_slug, provider_key, filtered)

    def get_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
    ) -> Mapping[str, str]:
        tenant_config = self._config.get(tenant_ctx.tenant_slug)
        if not isinstance(tenant_config, Mapping) and self._allow_wildcard:
            tenant_config = self._config.get("*")

        if not isinstance(tenant_config, Mapping):
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=provider_key,
                missing_fields=("provider credentials",),
            )

        provider_config = tenant_config.get(provider_key)
        if (
            not isinstance(provider_config, Mapping)
            and self._allow_wildcard
            and tenant_ctx.tenant_slug != "*"
        ):
            global_config = self._config.get("*")
            if isinstance(global_config, Mapping):
                provider_config = global_config.get(provider_key)

        if not isinstance(provider_config, Mapping):
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=provider_key,
                missing_fields=("provider credentials",),
            )

        credentials: dict[str, str] = {}
        for key, value in provider_config.items():
            if isinstance(key, str) and isinstance(value, str) and value:
                credentials[key] = value

        if not credentials:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=provider_key,
                missing_fields=("provider credentials",),
            )

        return credentials


class DbCredentialProvider:
    def __init__(self, cipher: "FernetCipher | None" = None) -> None:
        self._cipher = cipher or FernetCipher()

    @staticmethod
    def _missing(tenant_slug: str, provider_key: str) -> MissingCredentialsError:
        return MissingCredentialsError(
            tenant_slug=tenant_slug,
            provider_key=provider_key,
            missing_fields=("provider credentials",),
        )

    def set_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
        credentials: Mapping[str, str],
    ) -> Mapping[str, object]:
        import json
        from payglue_backend.webhooks.models import TenantProviderCredential

        filtered = {
            key: value
            for key, value in credentials.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
        if not filtered:
            raise self._missing(tenant_ctx.tenant_slug, provider_key)

        plaintext = json.dumps(filtered)
        encrypted = self._cipher.encrypt(plaintext)
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        TenantProviderCredential.objects.update_or_create(
            tenant_slug=tenant_ctx.tenant_slug,
            provider_key=provider_key,
            defaults={"credentials_enc": encrypted},
        )

        return {
            "backend": "db",
            "document_path": f"db://{tenant_ctx.tenant_slug}/{provider_key}",
            "updated_at": now_iso,
            "masked_keys": sorted(filtered.keys()),
        }

    def get_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
    ) -> Mapping[str, str]:
        import json
        from payglue_backend.webhooks.models import TenantProviderCredential

        record = TenantProviderCredential.objects.filter(
            tenant_slug=tenant_ctx.tenant_slug,
            provider_key=provider_key,
        ).first()
        if record is None:
            raise self._missing(tenant_ctx.tenant_slug, provider_key)

        try:
            plaintext = self._cipher.decrypt(record.credentials_enc)
            credentials = json.loads(plaintext)
        except Exception as exc:
            raise self._missing(tenant_ctx.tenant_slug, provider_key) from exc

        if not isinstance(credentials, dict) or not credentials:
            raise self._missing(tenant_ctx.tenant_slug, provider_key)

        return {k: v for k, v in credentials.items() if isinstance(k, str) and isinstance(v, str)}


class FirestoreCredentialProvider:
    def __init__(
        self,
        *,
        cipher: FernetCipher | None = None,
        client: Any | None = None,
        collection_name: str | None = None,
    ) -> None:
        self._cipher = cipher or FernetCipher()
        self._client = client
        self._collection_name = collection_name or getattr(
            settings, "FIRESTORE_CREDENTIALS_COLLECTION", "tenant_provider_credentials"
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud import firestore
        except ImportError as exc:  # pragma: no cover - runtime dependency optional
            raise RuntimeError(
                "google-cloud-firestore is required when FIRESTORE_CREDENTIALS_ENABLED=1"
            ) from exc
        self._client = firestore.Client()
        return self._client

    def _doc_ref(self, tenant_slug: str, provider_key: str) -> Any:
        doc_key = f"{tenant_slug}--{provider_key}"
        return self._get_client().collection(self._collection_name).document(doc_key)

    @staticmethod
    def _missing(tenant_slug: str, provider_key: str) -> MissingCredentialsError:
        return MissingCredentialsError(
            tenant_slug=tenant_slug,
            provider_key=provider_key,
            missing_fields=("provider credentials",),
        )

    def set_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
        credentials: Mapping[str, str],
    ) -> Mapping[str, object]:
        filtered = {
            key: value
            for key, value in credentials.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
        if not filtered:
            raise self._missing(tenant_ctx.tenant_slug, provider_key)

        encrypted = {
            key: self._cipher.encrypt(value) for key, value in filtered.items()
        }
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        doc_ref = self._doc_ref(tenant_ctx.tenant_slug, provider_key)
        doc_ref.set(
            {
                "tenant_slug": tenant_ctx.tenant_slug,
                "provider_key": provider_key,
                "credentials": encrypted,
                "updated_at": now_iso,
            },
            merge=True,
        )
        return {
            "backend": "firestore",
            "document_path": getattr(
                doc_ref,
                "path",
                f"{self._collection_name}/{tenant_ctx.tenant_slug}--{provider_key}",
            ),
            "updated_at": now_iso,
            "masked_keys": sorted(filtered.keys()),
        }

    def get_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
    ) -> Mapping[str, str]:
        snapshot = self._doc_ref(tenant_ctx.tenant_slug, provider_key).get()
        if not getattr(snapshot, "exists", False):
            raise self._missing(tenant_ctx.tenant_slug, provider_key)

        payload = snapshot.to_dict()
        encrypted = payload.get("credentials") if isinstance(payload, dict) else None
        if not isinstance(encrypted, dict):
            raise self._missing(tenant_ctx.tenant_slug, provider_key)

        credentials: dict[str, str] = {}
        try:
            for key, value in encrypted.items():
                if isinstance(key, str) and isinstance(value, str):
                    credentials[key] = self._cipher.decrypt(value)
        except ValueError as exc:
            raise self._missing(tenant_ctx.tenant_slug, provider_key) from exc

        if not credentials:
            raise self._missing(tenant_ctx.tenant_slug, provider_key)
        return credentials
