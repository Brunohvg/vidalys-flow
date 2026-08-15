import uuid

import pytest
from django.urls import reverse

from apps.customers.exceptions import InvalidDocumentError
from apps.orders import quick_views
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def test_quick_order_customer_domain_error_is_rendered_not_500(
    client,
    user,
    operator_membership,
    monkeypatch,
):
    def fail_customer_validation(**kwargs):
        raise InvalidDocumentError("Documento inválido para o cliente.")

    monkeypatch.setattr(quick_views, "create_quick_order", fail_customer_validation)
    client.force_login(user)

    response = client.post(
        reverse("orders:create"),
        {
            "customer_name": "Cliente inválido",
            "pricing_mode": Order.PricingMode.MANUAL,
            "manual_total": "50.00",
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 200
    assert "Documento inválido para o cliente." in response.content.decode()
