# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import logging
import os

from celery import Celery
from celery.signals import worker_ready


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "payglue_backend.config.settings")

app = Celery("payglue_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_ready.connect
def _warn_when_the_worker_cannot_send_mail(**_kwargs) -> None:
    """PG-326. The worker sends the delivery alert, so it needs the mail
    settings the web process has. Where the two run as separate services, the
    settings can be present on one and missing on the other, and nothing fails
    loudly, because the alert is best effort by design. This does not stop the
    worker, a purchase must still reach Ghost without a mail key, but it puts
    one unmissable line at the top of every start log.
    """
    from django.conf import settings

    backend = getattr(settings, "EMAIL_BACKEND", "")
    missing = []
    if backend.endswith("ResendAPIEmailBackend") and not getattr(settings, "RESEND_API_KEY", ""):
        missing.append("RESEND_API_KEY")
    if "localhost" in (getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""):
        missing.append("DEFAULT_FROM_EMAIL")
    if not getattr(settings, "PUBLIC_APP_BASE_URL", ""):
        missing.append("PUBLIC_APP_BASE_URL")
    if missing:
        logging.getLogger(__name__).error(
            "worker cannot send mail properly, missing: %s. Delivery alerts will "
            "stay pending until the nightly job sends them.",
            ", ".join(missing),
        )
