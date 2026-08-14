import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.fulfillment.models import Fulfillment
from apps.messaging import services
from apps.messaging.exceptions import (
    InvalidMessage,
    MessagingPermissionDenied,
    OrganizationMismatch,
    ProviderEffectsDisabled,
)
from apps.messaging.models import (
    Message,
    MessageCommandReceipt,
    MessageStatusHistory,
    MessageTemplate,
    MessagingChannel,
    MessagingPreference,
    MessagingProviderConnection,
)
from apps.messaging.tests.conftest import key
from apps.orders.models import Order
from apps.organizations.models import Membership
from apps.payments.models import PaymentIntent

pytestmark = pytest.mark.django_db


def test_manual_message_creation_is_successful(
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
    assert message.status == Message.Status.PENDING
    assert message.attempts.count() == 1
    assert message.template_semantic_key == "order_confirmation"
    assert message.destination_snapshot == contact.normalized_value
    assert message.parameter_snapshot == {"customer_name": "Cliente Messaging", "order_number": "PED-000051"}
    assert MessageStatusHistory.objects.filter(message=message).count() == 1
    assert organization.outbox_events.filter(event_type="messaging.message_created").count() == 1


def test_operator_can_request_manual_send(
    organization,
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
        actor=user,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    assert message.created_by == user


def test_manual_send_rejects_non_member(
    organization, outsider, messaging_order, messaging_customer, whatsapp_template, whatsapp_channel, allowed_preference
):
    _, contact = messaging_customer
    with pytest.raises(MessagingPermissionDenied):
        services.create_message_from_command(
            organization=organization,
            actor=outsider,
            source_type=Message.SourceType.ORDER,
            source_id=messaging_order.id,
            purpose="order_confirmation",
            template=whatsapp_template,
            channel=whatsapp_channel,
            contact_point=contact,
            idempotency_key=key(),
        )


def test_manual_send_rejects_unconfirmed_order(
    organization,
    manager,
    manager_membership,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    draft = Order.objects.create(
        organization=organization,
        number=99,
        customer=contact.customer,
        status=Order.Status.DRAFT,
        currency="BRL",
        total=0,
        created_by=manager,
    )
    with pytest.raises(InvalidMessage, match="confirmado"):
        services.create_message_from_command(
            organization=organization,
            actor=manager,
            source_type=Message.SourceType.ORDER,
            source_id=draft.id,
            purpose="order_confirmation",
            template=whatsapp_template,
            channel=whatsapp_channel,
            contact_point=contact,
            idempotency_key=key(),
        )


def test_manual_send_fails_closed_without_permission_evidence(
    organization, manager, manager_membership, messaging_order, messaging_customer, whatsapp_template, whatsapp_channel
):
    _, contact = messaging_customer
    with pytest.raises(InvalidMessage, match="permissão"):
        services.create_message_from_command(
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


def test_manual_send_fails_closed_on_suppression(
    organization, manager, manager_membership, messaging_order, messaging_customer, whatsapp_template, whatsapp_channel
):
    _, contact = messaging_customer
    MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact,
        channel=MessagingChannel.Kind.WHATSAPP,
        purpose="order_confirmation",
        decision=MessagingPreference.Decision.SUPPRESSED,
        provenance="opt_out",
        policy_version=1,
        effective_at=timezone.now(),
        is_active=True,
    )
    with pytest.raises(InvalidMessage, match="suprimido"):
        services.create_message_from_command(
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


def test_manual_send_rejects_merged_customer(
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
    target = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Alvo do merge",
    )
    contact.customer.merged_into = target
    contact.customer.save(update_fields=("merged_into",))
    with pytest.raises(InvalidMessage, match="mesclado"):
        services.create_message_from_command(
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


def test_manual_send_rejects_inactive_contact(
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
    contact.is_active = False
    contact.save(update_fields=("is_active",))
    with pytest.raises(InvalidMessage, match="inativo"):
        services.create_message_from_command(
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


def test_manual_send_rejects_cross_organization_channel(
    organization,
    other_organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    allowed_preference,
):
    _, contact = messaging_customer
    foreign_connection = MessagingProviderConnection.objects.create(
        organization=other_organization,
        provider="evolution",
        mode="linked_device",
        display_name="Conexão estrangeira",
        credential_alias="foreign-alias",
        is_active=True,
    )
    foreign = MessagingChannel.objects.create(
        organization=other_organization,
        connection=foreign_connection,
        kind=MessagingChannel.Kind.WHATSAPP,
        display_name="Canal estrangeiro",
        state=MessagingChannel.State.ACTIVE,
    )
    with pytest.raises(OrganizationMismatch):
        services.create_message_from_command(
            organization=organization,
            actor=manager,
            source_type=Message.SourceType.ORDER,
            source_id=messaging_order.id,
            purpose="order_confirmation",
            template=whatsapp_template,
            channel=foreign,
            contact_point=contact,
            idempotency_key=key(),
        )


def test_manual_send_is_idempotent(
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
    idempotency_key = key()
    first = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=idempotency_key,
    )
    second = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=idempotency_key,
    )
    assert first.id == second.id
    assert Message.objects.count() == 1
    assert MessageCommandReceipt.objects.get(idempotency_key=idempotency_key).completed


def test_checkout_link_manual_send_requires_active_link(
    organization,
    manager,
    manager_membership,
    messaging_customer,
    checkout_template,
    whatsapp_channel,
    allowed_checkout_preference,
    active_checkout_intent,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.PAYMENT,
        source_id=active_checkout_intent.id,
        purpose="checkout_link",
        template=checkout_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    assert "checkout_link" not in message.parameter_snapshot


def test_checkout_link_manual_send_rejects_stale_link(
    organization,
    manager,
    manager_membership,
    messaging_customer,
    checkout_template,
    whatsapp_channel,
    allowed_checkout_preference,
    active_checkout_intent,
):
    _, contact = messaging_customer
    active_checkout_intent.status = PaymentIntent.Status.REQUIRES_ATTENTION
    active_checkout_intent.attention_code = "replaced"
    active_checkout_intent.save(update_fields=("status", "attention_code"))
    with pytest.raises(InvalidMessage, match="link ativo"):
        services.create_message_from_command(
            organization=organization,
            actor=manager,
            source_type=Message.SourceType.PAYMENT,
            source_id=active_checkout_intent.id,
            purpose="checkout_link",
            template=checkout_template,
            channel=whatsapp_channel,
            contact_point=contact,
            idempotency_key=key(),
        )


def test_checkout_link_manual_send_rejects_template_without_checkout_parameter(
    organization,
    manager,
    manager_membership,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_checkout_preference,
    active_checkout_intent,
):
    _, contact = messaging_customer
    with pytest.raises(InvalidMessage, match="checkout_link"):
        services.create_message_from_command(
            organization=organization,
            actor=manager,
            source_type=Message.SourceType.PAYMENT,
            source_id=active_checkout_intent.id,
            purpose="checkout_link",
            template=whatsapp_template,
            channel=whatsapp_channel,
            contact_point=contact,
            idempotency_key=key(),
        )


def test_cancel_message_requires_manager(
    organization,
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
        actor=user,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    with pytest.raises(MessagingPermissionDenied):
        services.cancel_message(
            organization=organization,
            actor=user,
            message=message,
            expected_version=message.version,
            idempotency_key=key(),
        )


def test_cancel_message_transitions_to_cancelled(
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
    services.cancel_message(
        organization=organization,
        actor=manager,
        message=message,
        expected_version=message.version,
        idempotency_key=key(),
    )
    message.refresh_from_db()
    assert message.status == Message.Status.CANCELLED
    assert message.attempts.get().status == "cancelled"


def test_create_template_rejects_placeholder_outside_schema(organization, manager, manager_membership):
    with pytest.raises(InvalidMessage):
        services.create_template(
            organization=organization,
            actor=manager,
            semantic_key="broken",
            name="Quebrado",
            channel=MessageTemplate.Channel.WHATSAPP,
            locale="pt-BR",
            body_text="Olá {customer_name} {order_number}",
            body_html="",
            parameter_schema=["customer_name"],
            provider_template_reference="",
            idempotency_key=key(),
        )


def test_record_preference_supersedes_previous(
    organization, manager, manager_membership, messaging_customer, allowed_preference
):
    _, contact = messaging_customer
    services.record_preference(
        organization=organization,
        actor=manager,
        contact_point=contact,
        channel=MessagingChannel.Kind.WHATSAPP,
        purpose="order_confirmation",
        decision=MessagingPreference.Decision.SUPPRESSED,
        provenance="opt_out",
        policy_version=2,
        idempotency_key=key(),
    )
    active = MessagingPreference.objects.filter(
        organization=organization,
        contact_point=contact,
        channel="whatsapp",
        purpose="order_confirmation",
        is_active=True,
    )
    assert active.count() == 1
    assert active.get().decision == MessagingPreference.Decision.SUPPRESSED
    assert MessagingPreference.objects.filter(contact_point=contact).count() == 2


def test_record_preference_rejects_cross_organization_contact(
    organization, other_organization, manager, manager_membership, messaging_customer
):
    _, contact = messaging_customer
    Membership.objects.create(
        organization=other_organization,
        user=manager,
        role=Membership.Role.MANAGER,
    )
    with pytest.raises(OrganizationMismatch):
        services.record_preference(
            organization=other_organization,
            actor=manager,
            contact_point=contact,
            channel=MessagingChannel.Kind.WHATSAPP,
            purpose="order_confirmation",
            decision=MessagingPreference.Decision.ALLOWED,
            provenance="consent",
            policy_version=1,
            idempotency_key=key(),
        )


def test_manager_configures_connection_channel_template_and_rule(
    organization, manager, manager_membership, messaging_order, messaging_customer
):
    connection = services.create_provider_connection(
        organization=organization,
        actor=manager,
        provider="evolution",
        mode="linked_device",
        display_name="Evolution isolada",
        credential_alias="opaque-alias",
        idempotency_key=key(),
    )
    assert not connection.is_active
    connection = services.set_provider_connection_active(
        organization=organization,
        actor=manager,
        connection=connection,
        expected_version=connection.version,
        is_active=True,
        idempotency_key=key(),
    )
    channel = services.create_channel(
        organization=organization,
        actor=manager,
        connection=connection,
        kind="whatsapp",
        display_name="Canal isolado",
        credential_alias="opaque-channel-alias",
        idempotency_key=key(),
    )
    assert channel.state == MessagingChannel.State.PAIRING_REQUIRED
    assert channel.external_channel_id.startswith("vf-")
    template = services.create_template(
        organization=organization,
        actor=manager,
        semantic_key="configured_order",
        name="Pedido configurado",
        channel="whatsapp",
        locale="pt-BR",
        body_text="Olá {customer_name}, pedido {order_number}.",
        body_html="",
        parameter_schema=["customer_name", "order_number"],
        provider_template_reference="",
        idempotency_key=key(),
    )
    rule = services.upsert_automation_rule(
        organization=organization,
        actor=manager,
        event_type="order.confirmed",
        template=template,
        channel=channel,
        purpose="order_confirmation",
        is_enabled=False,
        idempotency_key=key(),
    )
    assert not rule.is_enabled
    connection = services.set_provider_connection_active(
        organization=organization,
        actor=manager,
        connection=connection,
        expected_version=connection.version,
        is_active=False,
        idempotency_key=key(),
    )
    assert not connection.is_active


def test_provider_mode_and_channel_kind_fail_closed(organization, manager, manager_membership):
    with pytest.raises(ProviderEffectsDisabled):
        services.create_provider_connection(
            organization=organization,
            actor=manager,
            provider="evolution",
            mode="email",
            display_name="Inválida",
            credential_alias="opaque-alias",
            idempotency_key=key(),
        )


def test_template_versions_and_used_template_is_immutable(
    organization, manager, manager_membership, messaging_order, messaging_customer, whatsapp_channel, allowed_preference
):
    first = services.create_template(
        organization=organization,
        actor=manager,
        semantic_key="versioned",
        name="Versão 1",
        channel="whatsapp",
        locale="pt-BR",
        body_text="Olá {customer_name}, pedido {order_number}.",
        body_html="",
        parameter_schema=["customer_name", "order_number"],
        provider_template_reference="",
        idempotency_key=key(),
    )
    second = services.create_template(
        organization=organization,
        actor=manager,
        semantic_key="versioned",
        name="Versão 2",
        channel="whatsapp",
        locale="pt-BR",
        body_text="Pedido {order_number} para {customer_name}.",
        body_html="",
        parameter_schema=["order_number", "customer_name"],
        provider_template_reference="",
        idempotency_key=key(),
    )
    assert (first.version, second.version) == (1, 2)
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="order",
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=first,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    first.name = "Mutação proibida"
    with pytest.raises(TypeError):
        first.save()
    assert message.source_version == messaging_order.version


def test_manual_fulfillment_and_paid_payment_sources(
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_channel,
    active_checkout_intent,
):
    contact = messaging_customer[1]
    fulfillment = Fulfillment.objects.create(
        organization=organization,
        order=messaging_order,
        sequence=1,
        method=Fulfillment.Method.DELIVERY,
        status=Fulfillment.Status.READY,
        created_by=manager,
    )
    fulfillment_template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key="fulfillment_ready",
        name="Fulfillment pronto",
        channel="whatsapp",
        body_text="Olá {customer_name}, {order_number}: {fulfillment_status}.",
        parameter_schema=["customer_name", "order_number", "fulfillment_status"],
    )
    MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact,
        channel="whatsapp",
        purpose="fulfillment_progress",
        decision="allowed",
        provenance="consent",
        effective_at=timezone.now(),
    )
    fulfillment_message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="fulfillment",
        source_id=fulfillment.id,
        purpose="fulfillment_progress",
        template=fulfillment_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    assert fulfillment_message.parameter_snapshot["fulfillment_status"] == fulfillment.get_status_display()

    active_checkout_intent.status = PaymentIntent.Status.PAID
    active_checkout_intent.paid_at = timezone.now()
    active_checkout_intent.save(update_fields=("status", "paid_at"))
    payment_template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key="payment_paid",
        name="Pagamento confirmado",
        channel="whatsapp",
        body_text="Olá {customer_name}, {order_number}: {amount} {currency}.",
        parameter_schema=["customer_name", "order_number", "amount", "currency"],
    )
    MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact,
        channel="whatsapp",
        purpose="payment_confirmation",
        decision="allowed",
        provenance="consent",
        effective_at=timezone.now(),
    )
    payment_message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="payment",
        source_id=active_checkout_intent.id,
        purpose="payment_confirmation",
        template=payment_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    assert payment_message.parameter_snapshot["currency"] == "BRL"


def test_rule_update_template_deactivation_and_pairing_are_guarded(
    organization,
    manager,
    manager_membership,
    whatsapp_template,
    whatsapp_channel,
    evolution_connection,
):
    rule = services.upsert_automation_rule(
        organization=organization,
        actor=manager,
        event_type="order.confirmed",
        template=whatsapp_template,
        channel=whatsapp_channel,
        purpose="order_confirmation",
        is_enabled=False,
        idempotency_key=key(),
    )
    updated = services.upsert_automation_rule(
        organization=organization,
        actor=manager,
        event_type="order.confirmed",
        template=whatsapp_template,
        channel=whatsapp_channel,
        purpose="order_confirmation",
        is_enabled=True,
        idempotency_key=key(),
    )
    assert updated.id == rule.id and updated.version == 2 and updated.is_enabled
    with pytest.raises(ProviderEffectsDisabled):
        services.request_pairing(
            organization=organization,
            actor=manager,
            channel=whatsapp_channel,
            expected_version=whatsapp_channel.version,
            idempotency_key=key(),
        )
    fresh = MessageTemplate.objects.create(
        organization=organization,
        semantic_key="unused",
        name="Não usado",
        channel="whatsapp",
        body_text="Olá {customer_name}.",
        parameter_schema=["customer_name"],
    )
    deactivated = services.deactivate_template(
        organization=organization,
        actor=manager,
        template=fresh,
        expected_version=fresh.version,
        idempotency_key=key(),
    )
    assert not deactivated.is_active


def test_internal_contract_validators_fail_closed_on_invalid_relationships(
    organization,
    other_organization,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    customer, contact = messaging_customer
    missing_id = uuid.uuid4()

    with pytest.raises(InvalidMessage, match="Finalidade"):
        services._resolve_source(
            organization=organization,
            source_type="order",
            source_id=missing_id,
            purpose="invalid",
        )
    incompatible = (
        ("order", "payment_confirmation"),
        ("fulfillment", "order_confirmation"),
        ("payment", "order_confirmation"),
    )
    for source_type, purpose in incompatible:
        with pytest.raises(InvalidMessage, match="incompatível"):
            services._resolve_source(
                organization=organization,
                source_type=source_type,
                source_id=missing_id,
                purpose=purpose,
            )
    for source_type, purpose in (
        ("order", "order_confirmation"),
        ("fulfillment", "fulfillment_progress"),
        ("payment", "payment_confirmation"),
    ):
        with pytest.raises(OrganizationMismatch):
            services._resolve_source(
                organization=organization,
                source_type=source_type,
                source_id=missing_id,
                purpose=purpose,
            )
    with pytest.raises(InvalidMessage, match="Tipo de fonte"):
        services._resolve_source(
            organization=organization,
            source_type="unknown",
            source_id=missing_id,
            purpose="order_confirmation",
        )

    original_customer_id = contact.customer_id
    contact.customer_id = missing_id
    with pytest.raises(OrganizationMismatch):
        services._resolve_permission(
            organization=organization,
            customer=customer,
            contact_point=contact,
            channel_kind="whatsapp",
            purpose="order_confirmation",
        )
    contact.customer_id = original_customer_id
    original_kind = contact.kind
    contact.kind = "email"
    with pytest.raises(InvalidMessage, match="incompatível"):
        services._resolve_permission(
            organization=organization,
            customer=customer,
            contact_point=contact,
            channel_kind="whatsapp",
            purpose="order_confirmation",
        )
    contact.kind = original_kind
    MessagingPreference.objects.filter(id=allowed_preference.id).update(
        effective_at=timezone.now() + timedelta(days=1)
    )
    with pytest.raises(InvalidMessage, match="não vigente"):
        services._resolve_permission(
            organization=organization,
            customer=customer,
            contact_point=contact,
            channel_kind="whatsapp",
            purpose="order_confirmation",
        )

    original_template_org = whatsapp_template.organization_id
    whatsapp_template.organization_id = other_organization.id
    with pytest.raises(OrganizationMismatch):
        services._validate_template(
            organization=organization,
            template=whatsapp_template,
            channel_kind="whatsapp",
        )
    whatsapp_template.organization_id = original_template_org
    whatsapp_template.is_active = False
    with pytest.raises(InvalidMessage, match="inativo"):
        services._validate_template(
            organization=organization,
            template=whatsapp_template,
            channel_kind="whatsapp",
        )
    whatsapp_template.is_active = True
    with pytest.raises(InvalidMessage, match="incompatível"):
        services._validate_template(
            organization=organization,
            template=whatsapp_template,
            channel_kind="email",
        )

    original_channel_org = whatsapp_channel.organization_id
    whatsapp_channel.organization_id = other_organization.id
    with pytest.raises(OrganizationMismatch):
        services._validate_channel(
            organization=organization,
            channel=whatsapp_channel,
            channel_kind="whatsapp",
        )
    whatsapp_channel.organization_id = original_channel_org
    with pytest.raises(InvalidMessage, match="incompatível"):
        services._validate_channel(
            organization=organization,
            channel=whatsapp_channel,
            channel_kind="email",
        )
    whatsapp_channel.state = MessagingChannel.State.DISABLED
    with pytest.raises(InvalidMessage, match="não está ativo"):
        services._validate_channel(
            organization=organization,
            channel=whatsapp_channel,
            channel_kind="whatsapp",
        )
