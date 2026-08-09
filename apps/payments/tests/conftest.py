import socket
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.orders.models import Order
from apps.payments.models import PaymentProviderAccount


@pytest.fixture(autouse=True)
def block_provider_network(monkeypatch):
    original = socket.getaddrinfo
    blocked_suffixes = ("mercadopago.com", "pagar.me")

    def guarded_getaddrinfo(host, *args, **kwargs):
        normalized = host.decode() if isinstance(host, bytes) else str(host)
        if normalized.lower().rstrip(".").endswith(blocked_suffixes):
            raise AssertionError("Provider network is forbidden in the Payments test suite.")
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture
def payable_order(organization, manager):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente Payments",
    )
    return Order.objects.create(
        organization=organization,
        number=50,
        customer=customer,
        status=Order.Status.CONFIRMED,
        currency="BRL",
        subtotal=Decimal("125.40"),
        total=Decimal("125.40"),
        customer_name_snapshot=customer.display_name,
        created_by=manager,
        confirmed_at=timezone.now(),
    )


@pytest.fixture
def mercado_account(organization):
    return PaymentProviderAccount.objects.create(
        organization=organization,
        provider=PaymentProviderAccount.Provider.MERCADO_PAGO,
        display_name="Mercado Pago principal",
        credential_alias=f"payments-test-{uuid.uuid4()}",
        is_active=True,
        callbacks_enabled=True,
    )
