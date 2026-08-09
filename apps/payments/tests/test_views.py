import uuid

import pytest
from django.urls import reverse

from apps.organizations.models import Membership
from apps.payments.models import PaymentIntent
from apps.payments.providers import CheckoutResult
from apps.payments.services import activate_hosted_checkout, create_payment_intent, request_hosted_checkout


def key():
    return str(uuid.uuid4())


@pytest.mark.django_db
def test_pages_require_authentication(client):
    assert client.get(reverse("payments:list")).status_code == 302


@pytest.mark.django_db
def test_manager_creates_intent_and_requests_checkout(
    client, organization, payable_order, mercado_account, manager, manager_membership
):
    client.force_login(manager)
    response = client.post(
        reverse("payments:create", args=(payable_order.id,)),
        {"idempotency_key": key()},
    )
    payment = PaymentIntent.objects.get()
    assert response.status_code == 302
    response = client.post(
        reverse("payments:request_checkout", args=(payment.id,)),
        {
            "provider_account": mercado_account.id,
            "expected_version": 1,
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    assert payment.attempts.count() == 1


@pytest.mark.django_db
def test_operator_can_view_and_copy_link_but_cannot_see_provider_evidence(
    client,
    organization,
    payable_order,
    mercado_account,
    user,
    operator_membership,
    manager,
    manager_membership,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
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
        result=CheckoutResult("private-resource-id", "https://checkout.example.test/operator-link"),
        idempotency_key=key(),
    )
    client.force_login(user)
    response = client.get(reverse("payments:detail", args=(intent.id,)))
    content = response.content.decode()
    assert response.status_code == 200
    assert "operator-link" in content
    assert "private-resource-id" not in content
    assert "Cliente Payments" not in content
    assert client.get(reverse("payments:create", args=(payable_order.id,))).status_code == 404


@pytest.mark.django_db
def test_cross_organization_payment_is_404(
    client,
    organization,
    other_organization,
    payable_order,
    manager,
    manager_membership,
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=key(),
    )
    other_user = type(manager).objects.create_user("other-payment@example.com", "safe-test-password")
    Membership.objects.create(
        organization=other_organization,
        user=other_user,
        role=Membership.Role.MANAGER,
    )
    client.force_login(other_user)
    assert client.get(reverse("payments:detail", args=(intent.id,))).status_code == 404


@pytest.mark.django_db
def test_callback_endpoint_is_generic_and_disabled_without_secret_channel(client, mercado_account):
    url = reverse("payments:mercado_pago_callback", args=(mercado_account.id,))
    assert client.post(url, data="{}", content_type="text/plain").status_code == 415
    response = client.post(
        url,
        data='{"id":"event","data":{"id":"resource"}}',
        content_type="application/json",
        HTTP_X_REQUEST_ID="req",
        HTTP_X_SIGNATURE="ts=1,v1=invalid",
    )
    assert response.status_code == 503
