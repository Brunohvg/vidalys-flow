import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.payments.models import PaymentAttempt, PaymentProviderAccount, PaymentStatusHistory
from apps.payments.providers import CheckoutResult
from apps.payments.selectors import payment_detail, payments_for_organization
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
