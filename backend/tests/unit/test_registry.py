import pytest

from payglue_backend.core.errors import (
    AdapterAlreadyRegisteredError,
    AdapterNotRegisteredError,
)
from payglue_backend.core.registry import AdapterRegistry


def test_adapter_registry_raises_for_unknown_payment_key() -> None:
    registry = AdapterRegistry()

    with pytest.raises(AdapterNotRegisteredError) as exc_info:
        registry.get_payment("missing")

    assert exc_info.value.adapter_type == "payment"
    assert exc_info.value.key == "missing"


def test_adapter_registry_rejects_duplicate_payment_registration() -> None:
    class _PaymentAdapter:
        pass

    registry = AdapterRegistry()
    registry.register_payment("polar", _PaymentAdapter())

    with pytest.raises(AdapterAlreadyRegisteredError) as exc_info:
        registry.register_payment("polar", _PaymentAdapter())

    assert exc_info.value.adapter_type == "payment"
    assert exc_info.value.key == "polar"


def test_adapter_registry_rejects_duplicate_cms_registration() -> None:
    class _CmsAdapter:
        pass

    registry = AdapterRegistry()
    registry.register_cms("ghost", _CmsAdapter())

    with pytest.raises(AdapterAlreadyRegisteredError) as exc_info:
        registry.register_cms("ghost", _CmsAdapter())

    assert exc_info.value.adapter_type == "cms"
    assert exc_info.value.key == "ghost"
