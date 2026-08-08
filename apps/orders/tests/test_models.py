from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.orders.models import Order, OrderItem


@pytest.mark.django_db
def test_database_rejects_invalid_item_formula(organization, order):
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItem.objects.create(
            organization=organization,
            order=order,
            position=1,
            name_snapshot="Inválido",
            unit_snapshot="un",
            quantity=Decimal("1"),
            unit_price=Decimal("10"),
            gross_total=Decimal("10"),
            discount_amount=Decimal("0"),
            surcharge_amount=Decimal("0"),
            total=Decimal("9"),
        )


@pytest.mark.django_db
def test_non_draft_order_cannot_be_deleted(organization, order):
    Order.objects.filter(id=order.id).update(
        status=Order.Status.CANCELLED,
        cancelled_at=order.created_at,
        cancel_reason="Motivo",
    )
    order.refresh_from_db()
    with pytest.raises(TypeError):
        order.delete()
