import uuid

import pytest
from django.urls import reverse

from apps.messaging import services
from apps.messaging.exceptions import MessagingPermissionDenied
from apps.messaging.models import Message

pytestmark = pytest.mark.django_db


def _payload(*, intent, template, channel, contact):
    return {
        "source_type": "payment",
        "source_id": intent.id,
        "purpose": "checkout_link",
        "template": template.id,
        "channel": channel.id,
        "contact_point": contact.id,
        "idempotency_key": str(uuid.uuid4()),
    }


def _service_payload(*, intent, template, channel, contact):
    return {
        "source_type": "payment",
        "source_id": intent.id,
        "purpose": "checkout_link",
        "template": template,
        "channel": channel,
        "contact_point": contact,
        "idempotency_key": str(uuid.uuid4()),
    }


def test_operator_cannot_request_checkout_link_send_from_http(
    client,
    user,
    operator_membership,
    active_checkout_intent,
    checkout_template,
    whatsapp_channel,
    messaging_customer,
    allowed_checkout_preference,
):
    client.force_login(user)

    response = client.post(
        reverse("messaging:send"),
        _payload(
            intent=active_checkout_intent,
            template=checkout_template,
            channel=whatsapp_channel,
            contact=messaging_customer[1],
        ),
    )

    assert response.status_code == 404
    assert not Message.objects.filter(purpose="checkout_link").exists()


def test_manager_can_request_checkout_link_send_from_http(
    client,
    manager,
    manager_membership,
    active_checkout_intent,
    checkout_template,
    whatsapp_channel,
    messaging_customer,
    allowed_checkout_preference,
):
    client.force_login(manager)

    response = client.post(
        reverse("messaging:send"),
        _payload(
            intent=active_checkout_intent,
            template=checkout_template,
            channel=whatsapp_channel,
            contact=messaging_customer[1],
        ),
    )

    assert response.status_code == 302
    assert Message.objects.filter(purpose="checkout_link", source_id=active_checkout_intent.id).exists()


def test_operator_cannot_bypass_checkout_authorization_through_service(
    organization,
    user,
    operator_membership,
    active_checkout_intent,
    checkout_template,
    whatsapp_channel,
    messaging_customer,
    allowed_checkout_preference,
):
    with pytest.raises(MessagingPermissionDenied):
        services.create_message_from_command(
            organization=organization,
            actor=user,
            **_service_payload(
                intent=active_checkout_intent,
                template=checkout_template,
                channel=whatsapp_channel,
                contact=messaging_customer[1],
            ),
        )

    assert not Message.objects.filter(purpose="checkout_link").exists()


def test_manager_can_create_checkout_message_through_service(
    organization,
    manager,
    manager_membership,
    active_checkout_intent,
    checkout_template,
    whatsapp_channel,
    messaging_customer,
    allowed_checkout_preference,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        **_service_payload(
            intent=active_checkout_intent,
            template=checkout_template,
            channel=whatsapp_channel,
            contact=messaging_customer[1],
        ),
    )

    assert message.purpose == "checkout_link"
    assert message.source_id == active_checkout_intent.id
