# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Give back the credential note a second Save could erase.

Until this release a connection update from the dashboard replaced the whole
metadata with the copy the page had loaded, and a second Save without a reload
sent a copy from before the first one. The note which credentials are stored
(`credential_ref`) was lost, and after the next reload the saved fields showed
as empty, although the credentials were still there. Gumroad, whose Save
registers its webhooks again, was the provider this happened with.

For every connection that has stored credentials but no note, the note is
rebuilt from the field names of the stored credentials. The values are never
written anywhere. A row that cannot be decrypted is left as it is.
"""
import json
from datetime import datetime, timezone

from django.db import migrations


def restore(apps, schema_editor):
    IntegrationConfig = apps.get_model("webhooks", "IntegrationConfig")
    TenantProviderCredential = apps.get_model("webhooks", "TenantProviderCredential")
    try:
        from payglue_backend.webhooks.credentials import FernetCipher

        cipher = FernetCipher()
    except Exception:
        # No encryption key configured (a fresh install, a test run without
        # one): nothing stored could be read, so nothing to restore.
        return

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    for config in IntegrationConfig.objects.exclude(provider_key="cms"):
        metadata = config.metadata if isinstance(config.metadata, dict) else {}
        if metadata.get("credential_ref"):
            continue
        record = TenantProviderCredential.objects.filter(
            tenant_slug=config.tenant_slug, provider_key=config.provider_type
        ).first()
        if record is None:
            continue
        try:
            stored = json.loads(cipher.decrypt(record.credentials_enc))
        except Exception:
            continue
        if not isinstance(stored, dict):
            continue
        keys = sorted(k for k, v in stored.items() if isinstance(k, str) and isinstance(v, str) and v)
        if not keys:
            continue
        config.metadata = {
            **metadata,
            "credential_ref": {"backend": "db", "updated_at": now_iso, "masked_keys": keys},
        }
        config.save(update_fields=["metadata"])


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0028_webhookinboundevent_signature_verified"),
    ]

    operations = [
        migrations.RunPython(restore, migrations.RunPython.noop),
    ]
