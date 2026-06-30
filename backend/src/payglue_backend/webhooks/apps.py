# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payglue_backend.webhooks"

    def ready(self) -> None:
        from payglue_backend.webhooks.wiring import get_webhook_orchestrator

        get_webhook_orchestrator()
