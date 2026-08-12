import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.payments.models import PaymentAttempt, PaymentIntent, PaymentProviderAccount, PaymentStatusHistory
from apps.payments.providers import CheckoutResult
from apps.payments.selectors import payment_detail, payments_for_organization, search_payments
from apps.payments.services import activate_hosted_checkout, create_payment_intent, request_hosted_checkout


def key():
    return str(uuid.uuid4())


@pytest.mark.django_db
def test_financial_records_and_history_are_immutable(organization, payable_order, manager, manager_membership):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    history = intent.status_history.get()
    with pytest.raises(TypeError):
        intent.delete()
    with pytest.raises(TypeError):
        history.save()
    with pytest.raises(TypeError):
        PaymentStatusHistory.objects.filter(id=history.id).update(source="tampered")


@pytest.mark.django_db
def test_payment_intent_snapshots_are_immutable_through_every_orm_write_path(
    organization, payable_order, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    intent.status = PaymentIntent.Status.PAID
    intent.paid_at = timezone.now()
    intent.save(update_fields=("status", "paid_at", "updated_at"))

    intent.amount = Decimal("1.00")
    with pytest.raises(TypeError, match="imutáveis"):
        intent.save()
    intent.refresh_from_db()

    with pytest.raises(TypeError, match="imutáveis"):
        PaymentIntent.objects.filter(id=intent.id).update(currency="USD")
    intent.order_number_snapshot = "PED-999999"
    with pytest.raises(TypeError, match="imutáveis"):
        PaymentIntent.objects.bulk_update([intent], ["order_number_snapshot"])


@pytest.mark.django_db(transaction=True)
def test_postgresql_trigger_rejects_snapshot_rewrite_bypassing_orm(
    organization, payable_order, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE payments_paymentintent SET amount = %s WHERE id = %s",
            [Decimal("2.00"), intent.id],
        )


@pytest.mark.django_db
def test_database_enforces_one_active_attempt(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    PaymentAttempt.objects.create(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        provider=mercado_account.provider,
        provider_idempotency_key=key(),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        PaymentAttempt.objects.create(
            organization=organization,
            intent=intent,
            provider_account=mercado_account,
            provider=mercado_account.provider,
            provider_idempotency_key=key(),
        )


@pytest.mark.django_db
def test_selectors_scope_and_mask_operator_detail(
    organization,
    other_organization,
    payable_order,
    mercado_account,
    user,
    operator_membership,
    manager,
    manager_membership,
):
    intent = create_payment_intent(organization=organization, order=payable_order, actor=manager, idempotency_key=key())
    attempt = request_hosted_checkout(
        organization=organization,
        intent=intent,
        provider_account=mercado_account,
        actor=manager,
        expected_version=1,
        idempotency_key=key(),
    )
    activate_hosted_checkout(
        organization=organization,
        attempt=attempt,
        result=CheckoutResult("external-private", "https://checkout.example.test/copy"),
        idempotency_key=key(),
    )
    detail = payment_detail(
        organization=organization,
        payment=intent,
        user=user,
        membership=operator_membership,
    )
    assert detail["customer_name"] == "••••"
    assert detail["attempts"][0]["hosted_url"].endswith("/copy")
    assert detail["attempts"][0]["external_resource_id"] == ""
    assert list(payments_for_organization(organization=other_organization)) == []
    assert list(
        search_payments(
            organization=organization,
            membership=operator_membership,
            query="Cliente Payments",
        )
    ) == []
    assert list(
        search_payments(
            organization=organization,
            membership=manager_membership,
            query="Cliente Payments",
        )
    ) == [intent]


@pytest.mark.django_db
def test_database_forbids_enabling_pagarme_callback(organization):
    with pytest.raises(IntegrityError), transaction.atomic():
        PaymentProviderAccount.objects.create(
            organization=organization,
            provider="pagarme",
            display_name="Pagar.me bloqueado",
            credential_alias="pagarme-constraint-test",
            is_active=True,
            callbacks_enabled=True,
        )
