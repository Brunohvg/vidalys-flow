import pytest

from apps.messaging import selectors, services
from apps.messaging.models import Message
from apps.messaging.tests.conftest import key
from apps.organizations.models import Membership

pytestmark = pytest.mark.django_db


def test_message_delete_is_forbidden(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    with pytest.raises(TypeError):
        message.delete()


def test_preference_is_immutable(organization, messaging_customer, allowed_preference):
    allowed_preference.provenance = "changed"
    with pytest.raises(TypeError):
        allowed_preference.save()


def test_email_destination_masking(organization, messaging_customer):
    _, _ = messaging_customer
    from apps.messaging.models import MessagingChannel

    assert (
        selectors._mask_destination("cliente@example.com", channel_kind=MessagingChannel.Kind.EMAIL)
        == "cl•••••@example.com"
    )
    assert selectors._mask_destination("a@example.com", channel_kind=MessagingChannel.Kind.EMAIL) == "a••@example.com"


def test_whatsapp_destination_masking():
    from apps.messaging.models import MessagingChannel

    assert selectors._mask_destination("+5511999998888", channel_kind=MessagingChannel.Kind.WHATSAPP) == "••••8888"
    assert selectors._mask_destination("", channel_kind=MessagingChannel.Kind.WHATSAPP) == "••••"


def test_search_messages_filters_by_status(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    assert selectors.search_messages(organization=organization, status="pending").filter(id=message.id).exists()
    assert not selectors.search_messages(organization=organization, status="delivered").filter(id=message.id).exists()


def test_message_detail_masks_for_operator(
    organization,
    manager,
    manager_membership,
    user,
    operator_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    operator_detail = selectors.message_detail(
        organization=organization,
        message=message,
        user=user,
        membership=operator_membership,
    )
    manager_detail = selectors.message_detail(
        organization=organization,
        message=message,
        user=manager,
        membership=manager_membership,
    )
    assert operator_detail["destination"] != contact.normalized_value
    assert manager_detail["destination"] == contact.normalized_value


def test_cross_organization_message_detail_is_none(
    organization,
    other_organization,
    manager,
    manager_membership,
    user,
    operator_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    other_user = type(manager).objects.create_user("other-messaging@example.com", "safe-test-password")
    other_membership = Membership.objects.create(
        organization=other_organization,
        user=other_user,
        role=Membership.Role.MANAGER,
    )
    assert (
        selectors.message_detail(
            organization=other_organization,
            message=message,
            user=other_user,
            membership=other_membership,
        )
        is None
    )
