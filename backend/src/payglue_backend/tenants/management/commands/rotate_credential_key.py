# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Re-encrypt every stored credential with the current encryption key.

Changing CREDENTIAL_ENCRYPTION_KEY works in three steps:

1. Set the new key as CREDENTIAL_ENCRYPTION_KEY and the old one as
   CREDENTIAL_ENCRYPTION_KEY_PREVIOUS, then deploy. Everything stays
   readable, new values are written with the new key.
2. Run this command, first without --apply to see the counts, then with it.
3. Remove CREDENTIAL_ENCRYPTION_KEY_PREVIOUS and deploy again.

Nothing is written unless every stored value can be read, so a wrong or
missing previous key stops the run before it changes anything. The output
never contains a credential, only row ids and counts.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from payglue_backend.tenants.models import NewsletterRouting
from payglue_backend.webhooks.credentials import FernetCipher
from payglue_backend.webhooks.models import TenantProviderCredential

# Every model field that holds a FernetCipher value.
ENCRYPTED_FIELDS = [
    (TenantProviderCredential, "credentials_enc"),
    (NewsletterRouting, "ghost_admin_api_key_enc"),
]


class Command(BaseCommand):
    help = "Re-encrypt all stored credentials with the current CREDENTIAL_ENCRYPTION_KEY."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the re-encrypted values. Without it nothing changes.")

    def handle(self, *args, **options):
        cipher = FernetCipher()
        pending: list[tuple[type, str, int, str]] = []
        unreadable: list[str] = []

        for model, field in ENCRYPTED_FIELDS:
            label = f"{model.__name__}.{field}"
            rows = model.objects.exclude(**{field: ""}).values_list("pk", field)
            total = current = 0
            for pk, value in rows.iterator():
                total += 1
                if cipher.is_current(value):
                    current += 1
                    continue
                try:
                    cipher.decrypt(value)
                except ValueError:
                    unreadable.append(f"{label} id={pk}")
                    continue
                pending.append((model, field, pk, value))
            self.stdout.write(f"{label}: {total} stored, {current} already on the current key")

        if unreadable:
            raise CommandError(
                "Cannot read with any configured key, nothing was changed: " + ", ".join(unreadable)
            )

        self.stdout.write(f"{len(pending)} value(s) to re-encrypt")
        if not options["apply"]:
            self.stdout.write("Dry run, nothing written. Run again with --apply.")
            return

        with transaction.atomic():
            for model, field, pk, value in pending:
                # update() rather than save(): no auto_now bump, no signals.
                model.objects.filter(pk=pk).update(**{field: cipher.rotate(value)})

        for model, field in ENCRYPTED_FIELDS:
            for pk, value in model.objects.exclude(**{field: ""}).values_list("pk", field).iterator():
                if not cipher.is_current(value):
                    raise CommandError(f"{model.__name__}.{field} id={pk} is not on the current key after the run")

        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {len(pending)} value(s). Every stored value is on the current key."))
