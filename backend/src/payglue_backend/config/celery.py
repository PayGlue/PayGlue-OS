# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "payglue_backend.config.settings")

app = Celery("payglue_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
