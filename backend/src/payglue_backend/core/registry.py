# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from payglue_backend.core.errors import (
    AdapterAlreadyRegisteredError,
    AdapterNotRegisteredError,
)
from payglue_backend.core.interfaces import CmsAdapter, PaymentAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._payment_adapters: dict[str, PaymentAdapter] = {}
        self._cms_adapters: dict[str, CmsAdapter] = {}

    def register_payment(self, key: str, adapter: PaymentAdapter) -> None:
        if key in self._payment_adapters:
            raise AdapterAlreadyRegisteredError("payment", key)
        self._payment_adapters[key] = adapter

    def register_cms(self, key: str, adapter: CmsAdapter) -> None:
        if key in self._cms_adapters:
            raise AdapterAlreadyRegisteredError("cms", key)
        self._cms_adapters[key] = adapter

    def get_payment(self, key: str) -> PaymentAdapter:
        try:
            return self._payment_adapters[key]
        except KeyError as exc:
            raise AdapterNotRegisteredError("payment", key) from exc

    def get_cms(self, key: str) -> CmsAdapter:
        try:
            return self._cms_adapters[key]
        except KeyError as exc:
            raise AdapterNotRegisteredError("cms", key) from exc
