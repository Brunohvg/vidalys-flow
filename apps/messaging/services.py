import hashlib
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.customers.models import ContactPoint, Customer
from apps.fulfillment.models import Fulfillment
from apps.messaging import policies
from apps.messaging.content import placeholders, render_message_body, validate_parameter_schema
from apps.messaging.events import (
    ALLOWLISTED_SOURCE_EVENTS,
    MESSAGE_CREATED,
    MESSAGE_STATUS_CHANGED,
    SOURCE_EVENT_CONTRACT_VERSIONS,
    SOURCE_EVENT_FULFILLMENT_COMPLETED,
    SOURCE_EVENT_FULFILLMENT_DISPATCHED,
    SOURCE_EVENT_FULFILLMENT_READY,
    SOURCE_EVENT_ORDER_CONFIRMED,
    SOURCE_EVENT_PAYMENT_CHECKOUT_ACTIVATED,
    SOURCE_EVENT_PAYMENT_STATUS_CHANGED,
)
from apps.messaging.exceptions import (
    IdempotencyConflict,
    InvalidMessage,
    MessagingDomainError,
    MessagingPermissionDenied,
    OrganizationMismatch,
    ProviderEffectsDisabled,
    VersionConflict,
)
from apps.messaging.idempotency import claim_command, complete_command
from apps.messaging.models import (
    Message,
    MessageAutomationRule,
    MessageDeliveryAttempt,
    MessageStatusHistory,
    MessageTemplate,
    MessageWebhookReceipt,
    MessagingChannel,
    MessagingPreference,
    MessagingProviderConnection,
)
from apps.messaging.providers import (
    HARD_FEEDBACK_STATUSES,
    SendRequest,
    assert_capability,
    evolution_instance_name,
    map_delivery_status,
    provider_capabilities,
    provider_channel_kind,
    require_network_allowed,
    validate_provider_mode,
)
from apps.messaging.template_catalog import validate_transactional_template
from apps.orders.models import Order
from apps.payments.models import PaymentAttempt, PaymentIntent
from apps.platform.services import enqueue_event

PURPOSE_ORDER_CONFIRMATION = "order_confirmation"
PURPOSE_FULFILLMENT_PROGRESS = "fulfillment_progress"
PURPOSE_PAYMENT_CONFIRMATION = "payment_confirmation"
PURPOSE_CHECKOUT_LINK = "checkout_link"

PURPOSES = frozenset(
    {
        PURPOSE_ORDER_CONFIRMATION,
        PURPOSE_FULFILLMENT_PROGRESS,
        PURPOSE_PAYMENT_CONFIRMATION,
        PURPOSE_CHECKOUT_LINK,
    }
)

DISPATCH_LEASE_SECONDS = 90
DISPATCH_RETRY_MAX_SECONDS = 300
TERMINAL_MESSAGE_STATUSES = frozenset({Message.Status.DELIVERED, Message.Status.FAILED, Message.Status.CANCELLED})
EVENT_PURPOSES = {
    SOURCE_EVENT_ORDER_CONFIRMED: PURPOSE_ORDER_CONFIRMATION,
    SOURCE_EVENT_FULFILLMENT_READY: PURPOSE_FULFILLMENT_PROGRESS,
    SOURCE_EVENT_FULFILLMENT_DISPATCHED: PURPOSE_FULFILLMENT_PROGRESS,
    SOURCE_EVENT_FULFILLMENT_COMPLETED: PURPOSE_FULFILLMENT_PROGRESS,
    SOURCE_EVENT_PAYMENT_CHECKOUT_ACTIVATED: PURPOSE_CHECKOUT_LINK,
    SOURCE_EVENT_PAYMENT_STATUS_CHANGED: PURPOSE_PAYMENT_CONFIRMATION,
}
WHATSAPP_CONTACT_KINDS = {ContactPoint.Kind.PHONE, ContactPoint.Kind.WHATSAPP}
EMAIL_CONTACT_KINDS = {ContactPoint.Kind.EMAIL}
EVENT_SOURCE_TYPES = {
    SOURCE_EVENT_ORDER_CONFIRMED: Message.SourceType.ORDER,
    SOURCE_EVENT_FULFILLMENT_READY: Message.SourceType.FULFILLMENT,
    SOURCE_EVENT_FULFILLMENT_DISPATCHED: Message.SourceType.FULFILLMENT,
    SOURCE_EVENT_FULFILLMENT_COMPLETED: Message.SourceType.FULFILLMENT,
    SOURCE_EVENT_PAYMENT_CHECKOUT_ACTIVATED: Message.SourceType.PAYMENT,
    SOURCE_EVENT_PAYMENT_STATUS_CHANGED: Message.SourceType.PAYMENT,
}
EVENT_AGGREGATE_TYPES = {
    SOURCE_EVENT_ORDER_CONFIRMED: "order",
    SOURCE_EVENT_FULFILLMENT_READY: "fulfillment",
    SOURCE_EVENT_FULFILLMENT_DISPATCHED: "fulfillment",
    SOURCE_EVENT_FULFILLMENT_COMPLETED: "fulfillment",
    SOURCE_EVENT_PAYMENT_CHECKOUT_ACTIVATED: "payment_intent",
    SOURCE_EVENT_PAYMENT_STATUS_CHANGED: "payment_intent",
}
EVENT_SOURCE_STATUSES = {
    SOURCE_EVENT_ORDER_CONFIRMED: Order.Status.CONFIRMED,
    SOURCE_EVENT_FULFILLMENT_READY: Fulfillment.Status.READY,
    SOURCE_EVENT_FULFILLMENT_DISPATCHED: Fulfillment.Status.IN_TRANSIT,
    SOURCE_EVENT_FULFILLMENT_COMPLETED: Fulfillment.Status.COMPLETED,
    SOURCE_EVENT_PAYMENT_CHECKOUT_ACTIVATED: PaymentIntent.Status.AWAITING_PAYMENT,
    SOURCE_EVENT_PAYMENT_STATUS_CHANGED: PaymentIntent.Status.PAID,
}
ALLOWED_EVIDENCE_FLAGS = frozenset({"has_delivery_ambiguity", "has_delivery_inconsistency"})


def _require_manager(*, actor, organization):
    if actor is None or not policies.can_configure_messaging(user=actor, organization=organization):
        raise MessagingPermissionDenied("Membership ativa de manager tier é obrigatória.")


def _require_member(*, actor, organization):
    if actor is None or not policies.can_request_manual_send(user=actor, organization=organization):
        raise MessagingPermissionDenied("Membership ativa é obrigatória.")


def _ensure_version(*, obj, expected_version):
    if obj.version != expected_version:
        raise VersionConflict(f"Registro alterado (versão atual {obj.version}, recebida {expected_version}).")


def _history(*, message, from_status, actor, command_id, source, reason_code=""):
    MessageStatusHistory.objects.create(
        organization=message.organization,
        message=message,
        from_status=from_status,
        to_status=message.status,
        actor=actor,
        command_id=str(command_id),
        source=source,
        reason_code=reason_code,
    )


def _audit(*, message, actor, action, payload=None):
    payload = payload or {}
    if set(payload) - ALLOWED_EVIDENCE_FLAGS or any(not isinstance(value, bool) for value in payload.values()):
        raise InvalidMessage("Payload de auditoria de Messaging fora do schema aprovado.")
    record_event(
        organization=message.organization,
        actor=actor,
        action=action,
        entity_type="message",
        entity_id=message.id,
        payload={
            "message_id": str(message.id),
            "purpose": message.purpose,
            "template_semantic_key": message.template_semantic_key,
            "channel_kind": message.channel_kind,
            "status": message.status,
            "version": message.version,
            **payload,
        },
    )


def _outbox(*, message, event_type, command_id, extra=None):
    extra = extra or {}
    if set(extra) - ALLOWED_EVIDENCE_FLAGS or any(not isinstance(value, bool) for value in extra.values()):
        raise InvalidMessage("Payload de evento de Messaging fora do schema aprovado.")
    enqueue_event(
        organization=message.organization,
        event_type=event_type,
        aggregate_type="message",
        aggregate_id=message.id,
        payload={
            "message_id": str(message.id),
            "purpose": message.purpose,
            "template_semantic_key": message.template_semantic_key,
            "channel_kind": message.channel_kind,
            "status": message.status,
            "version": message.version,
            **extra,
        },
        idempotency_key=f"message:{message.id}:{event_type}:{command_id}",
    )


def _existing_message(receipt):
    message = Message.objects.filter(organization=receipt.organization, id=receipt.message_id).first()
    if message is None:
        raise IdempotencyConflict("A Message resultante não existe.")
    return message


def _lock_message(*, organization, message_id):
    message = (
        Message.objects.select_for_update()
        .select_related("template", "channel", "channel__connection", "customer")
        .filter(organization=organization, id=message_id)
        .first()
    )
    if message is None:
        raise OrganizationMismatch("Message não pertence à organização.")
    return message


def _resolve_source(*, organization, source_type, source_id, purpose):
    if purpose not in PURPOSES:
        raise InvalidMessage("Finalidade de envio inválida.")
    if source_type == Message.SourceType.ORDER:
        if purpose != PURPOSE_ORDER_CONFIRMATION:
            raise InvalidMessage("Finalidade incompatível com pedido.")
        source = (
            Order.objects.select_for_update()
            .select_related("customer")
            .filter(organization=organization, id=source_id)
            .first()
        )
        if source is None:
            raise OrganizationMismatch("Pedido não pertence à organização.")
        if purpose == PURPOSE_ORDER_CONFIRMATION and source.status != Order.Status.CONFIRMED:
            raise InvalidMessage("Somente pedido confirmado pode originar confirmação de pedido.")
        customer = source.customer
        parameters = {
            "customer_name": source.customer_name_snapshot or customer.display_name,
            "order_number": source.display_number,
        }
    elif source_type == Message.SourceType.FULFILLMENT:
        if purpose != PURPOSE_FULFILLMENT_PROGRESS:
            raise InvalidMessage("Finalidade incompatível com Fulfillment.")
        source = (
            Fulfillment.objects.select_for_update()
            .select_related("order__customer")
            .filter(organization=organization, id=source_id)
            .first()
        )
        if source is None:
            raise OrganizationMismatch("Fulfillment não pertence à organização.")
        if purpose == PURPOSE_FULFILLMENT_PROGRESS and source.status not in {
            Fulfillment.Status.READY,
            Fulfillment.Status.IN_TRANSIT,
            Fulfillment.Status.COMPLETED,
        }:
            raise InvalidMessage("Fulfillment não está em progresso elegível para comunicação.")
        customer = source.order.customer
        parameters = {
            "customer_name": customer.display_name,
            "order_number": source.order.display_number,
            "fulfillment_status": source.get_status_display(),
        }
    elif source_type == Message.SourceType.PAYMENT:
        if purpose not in {PURPOSE_CHECKOUT_LINK, PURPOSE_PAYMENT_CONFIRMATION}:
            raise InvalidMessage("Finalidade incompatível com pagamento.")
        source = (
            PaymentIntent.objects.select_for_update()
            .select_related("order__customer")
            .filter(organization=organization, id=source_id)
            .first()
        )
        if source is None:
            raise OrganizationMismatch("Pagamento não pertence à organização.")
        if purpose == PURPOSE_CHECKOUT_LINK and source.status != PaymentIntent.Status.AWAITING_PAYMENT:
            raise InvalidMessage("Somente pagamento com link ativo pode compartilhar checkout.")
        if purpose == PURPOSE_PAYMENT_CONFIRMATION and source.status != PaymentIntent.Status.PAID:
            raise InvalidMessage("Somente pagamento pago pode originar confirmação de pagamento.")
        customer = source.order.customer
        parameters = {
            "customer_name": source.customer_name_snapshot or customer.display_name,
            "order_number": source.order_number_snapshot,
            "amount": str(source.amount),
            "currency": source.currency,
        }
    else:
        raise InvalidMessage("Tipo de fonte inválido.")
    return source, customer, parameters


def _contact_kinds_for(channel_kind):
    return WHATSAPP_CONTACT_KINDS if channel_kind == MessagingChannel.Kind.WHATSAPP else EMAIL_CONTACT_KINDS


def _resolve_permission(*, organization, customer, contact_point, channel_kind, purpose):
    if customer.status != Customer.Status.ACTIVE or customer.merged_into_id is not None:
        raise InvalidMessage("Customer inativo, bloqueado ou mesclado não pode receber envio.")
    if contact_point.customer_id != customer.id:
        raise OrganizationMismatch("ContactPoint não pertence ao customer da fonte.")
    if not contact_point.is_active:
        raise InvalidMessage("ContactPoint inativo não pode receber envio.")
    if contact_point.kind not in _contact_kinds_for(channel_kind):
        raise InvalidMessage("ContactPoint incompatível com o canal.")
    preference = (
        MessagingPreference.objects.filter(
            organization=organization,
            contact_point=contact_point,
            channel=channel_kind,
            purpose=purpose,
            is_active=True,
        )
        .order_by("-effective_at", "-created_at")
        .first()
    )
    if preference is None:
        raise InvalidMessage("Falta evidência de permissão vigente para esta finalidade.")
    if preference.decision != MessagingPreference.Decision.ALLOWED:
        raise InvalidMessage("Contato suprimido para esta finalidade.")
    if preference.effective_at > timezone.now():
        raise InvalidMessage("Evidência de permissão ainda não vigente.")
    return preference


def _validate_template(*, organization, template, channel_kind, purpose=None):
    if template.organization_id != organization.id:
        raise OrganizationMismatch("Template não pertence à organização.")
    if not template.is_active:
        raise InvalidMessage("Template inativo.")
    if template.channel != channel_kind:
        raise InvalidMessage("Template incompatível com o canal.")
    schema = validate_parameter_schema(template.parameter_schema)
    validate_transactional_template(
        semantic_key=template.semantic_key,
        channel=template.channel,
        locale=template.locale,
        body_text=template.body_text,
        body_html=template.body_html,
        parameter_schema=schema,
        purpose=purpose,
    )
    return schema


def _validate_channel(*, organization, channel, channel_kind):
    if channel.organization_id != organization.id:
        raise OrganizationMismatch("Canal não pertence à organização.")
    if channel.kind != channel_kind:
        raise InvalidMessage("Canal incompatível com o template.")
    if channel.state != MessagingChannel.State.ACTIVE:
        raise InvalidMessage("Canal não está ativo para envio.")
    if channel.connection.organization_id != organization.id or not channel.connection.is_active:
        raise InvalidMessage("Conexão do provider não está ativa para envio.")


def _resolve_primary_contact(*, customer, channel_kind):
    return (
        customer.contacts.filter(kind__in=_contact_kinds_for(channel_kind), is_active=True, is_primary=True)
        .order_by("created_at")
        .first()
    )


def _filter_parameters(*, parameters, schema):
    return {key: value for key, value in parameters.items() if key in schema}


def _create_message(
    *,
    organization,
    source_type,
    source_id,
    source_version,
    source_event_id,
    purpose,
    template,
    channel,
    customer,
    contact_point,
    permission,
    parameters,
    actor,
    idempotency_key,
    operation,
):
    schema = _validate_template(
        organization=organization,
        template=template,
        channel_kind=channel.kind,
        purpose=purpose,
    )
    _validate_channel(organization=organization, channel=channel, channel_kind=template.channel)
    needed = placeholders(template.body_text) | placeholders(template.body_html or "")
    if not needed.issubset(set(parameters) | {"checkout_link"}):
        raise InvalidMessage("Fonte não fornece todos os parâmetros exigidos pelo template.")
    payload = {
        "source_type": source_type,
        "source_id": str(source_id),
        "purpose": purpose,
        "template_id": str(template.id),
        "template_version": template.version,
        "channel_id": str(channel.id),
        "contact_point_id": str(contact_point.id),
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation=operation,
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
        source_event_id=source_event_id,
    )
    if not is_new:
        return _existing_message(receipt)
    snapshot = _filter_parameters(parameters=parameters, schema=schema)
    message = Message.objects.create(
        organization=organization,
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        source_event_id=source_event_id,
        purpose=purpose,
        template=template,
        template_semantic_key=template.semantic_key,
        template_version=template.version,
        channel=channel,
        channel_kind=channel.kind,
        locale=template.locale,
        customer=customer,
        customer_display_name=customer.display_name,
        contact_point=contact_point,
        destination_snapshot=contact_point.normalized_value,
        permission_evidence_id=permission.id,
        permission_policy_version=permission.policy_version,
        parameter_snapshot=snapshot,
        created_by=actor,
    )
    MessageDeliveryAttempt.objects.create(
        organization=organization,
        message=message,
        channel=channel,
        dispatch_key=str(message.id),
        provider_correlation_tag=f"vf:{channel.id}:{message.id}",
    )
    _history(message=message, from_status="", actor=actor, command_id=idempotency_key, source="command")
    _audit(message=message, actor=actor, action=MESSAGE_CREATED)
    _outbox(message=message, event_type=MESSAGE_CREATED, command_id=idempotency_key)
    complete_command(receipt=receipt, message=message)
    return message


@transaction.atomic
def create_message_from_command(
    *,
    organization,
    actor,
    source_type,
    source_id,
    purpose,
    template,
    channel,
    contact_point,
    idempotency_key,
):
    _require_member(actor=actor, organization=organization)
    if purpose == PURPOSE_CHECKOUT_LINK and "checkout_link" not in (template.parameter_schema or []):
        raise InvalidMessage("Compartilhar checkout exige template com parâmetro checkout_link.")
    source, customer, parameters = _resolve_source(
        organization=organization,
        source_type=source_type,
        source_id=source_id,
        purpose=purpose,
    )
    permission = _resolve_permission(
        organization=organization,
        customer=customer,
        contact_point=contact_point,
        channel_kind=template.channel,
        purpose=purpose,
    )
    return _create_message(
        organization=organization,
        source_type=source_type,
        source_id=source_id,
        source_version=source.version,
        source_event_id=None,
        purpose=purpose,
        template=template,
        channel=channel,
        customer=customer,
        contact_point=contact_point,
        permission=permission,
        parameters=parameters,
        actor=actor,
        idempotency_key=idempotency_key,
        operation="create_message_from_command",
    )


@transaction.atomic
def create_message_from_event(*, organization, rule, source_event_id, source_id, source_version, source_type, purpose):
    template = MessageTemplate.objects.filter(organization=organization, id=rule.template_id, is_active=True).first()
    if template is None:
        raise InvalidMessage("Template da regra está inativo.")
    channel = MessagingChannel.objects.filter(organization=organization, id=rule.channel_id).first()
    if channel is None:
        raise OrganizationMismatch("Canal da regra não pertence à organização.")
    source, customer, parameters = _resolve_source(
        organization=organization,
        source_type=source_type,
        source_id=source_id,
        purpose=purpose,
    )
    if source.version != source_version:
        raise InvalidMessage("Evento de origem está obsoleto para o agregado atual.")
    if source.status != EVENT_SOURCE_STATUSES[rule.event_type]:
        raise InvalidMessage("Estado atual da fonte é incompatível com o evento transacional.")
    contact_point = _resolve_primary_contact(customer=customer, channel_kind=channel.kind)
    if contact_point is None:
        raise InvalidMessage("Customer sem contato primário ativo para o canal.")
    permission = _resolve_permission(
        organization=organization,
        customer=customer,
        contact_point=contact_point,
        channel_kind=channel.kind,
        purpose=purpose,
    )
    digest = hashlib.sha256(
        f"{source_event_id}:{rule.id}:{rule.version}:{template.id}:{template.version}:{channel.id}:{contact_point.normalized_value}".encode()
    ).hexdigest()
    return _create_message(
        organization=organization,
        source_type=source_type,
        source_id=source_id,
        source_version=source.version,
        source_event_id=source_event_id,
        purpose=purpose,
        template=template,
        channel=channel,
        customer=customer,
        contact_point=contact_point,
        permission=permission,
        parameters=parameters,
        actor=None,
        idempotency_key=digest,
        operation="create_message_from_event",
    )


def consume_source_event(*, event):
    if event.event_type not in ALLOWLISTED_SOURCE_EVENTS:
        raise InvalidMessage("Evento de origem fora do allowlist.")
    organization = event.organization
    if organization is None:
        raise InvalidMessage("Evento sem organização.")
    purpose = EVENT_PURPOSES[event.event_type]
    source_type = EVENT_SOURCE_TYPES[event.event_type]
    event_contract_version = event.payload.get("event_contract_version")
    expected_contract_version = SOURCE_EVENT_CONTRACT_VERSIONS[event.event_type]
    if (
        isinstance(event_contract_version, bool)
        or not isinstance(event_contract_version, int)
        or event_contract_version != expected_contract_version
    ):
        raise InvalidMessage("Versão do contrato do evento ausente ou incompatível.")
    if event.aggregate_type != EVENT_AGGREGATE_TYPES[event.event_type]:
        raise InvalidMessage("Tipo do agregado não corresponde ao contrato do evento.")
    source_id = event.payload.get(
        {
            SOURCE_EVENT_ORDER_CONFIRMED: "order_id",
            SOURCE_EVENT_FULFILLMENT_READY: "fulfillment_id",
            SOURCE_EVENT_FULFILLMENT_DISPATCHED: "fulfillment_id",
            SOURCE_EVENT_FULFILLMENT_COMPLETED: "fulfillment_id",
            SOURCE_EVENT_PAYMENT_CHECKOUT_ACTIVATED: "payment_intent_id",
            SOURCE_EVENT_PAYMENT_STATUS_CHANGED: "payment_intent_id",
        }[event.event_type]
    )
    if not source_id:
        raise InvalidMessage("Evento de origem sem identificador da fonte.")
    if str(source_id) != str(event.aggregate_id):
        raise InvalidMessage("Identificador do agregado diverge do payload do evento.")
    source_version = event.payload.get("version")
    if isinstance(source_version, bool) or not isinstance(source_version, int) or source_version < 1:
        raise InvalidMessage("Evento de origem sem versão válida.")
    rules = MessageAutomationRule.objects.filter(
        organization=organization,
        event_type=event.event_type,
        event_version=event_contract_version,
        is_enabled=True,
    ).select_related("template", "channel")
    created = 0
    for rule in rules:
        try:
            create_message_from_event(
                organization=organization,
                rule=rule,
                source_event_id=event.id,
                source_id=source_id,
                source_version=source_version,
                source_type=source_type,
                purpose=purpose,
            )
            created += 1
        except (InvalidMessage, OrganizationMismatch, IdempotencyConflict):
            continue
    return created


@transaction.atomic
def claim_dispatch(*, attempt_id):
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não está aguardando envio.")
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = (
        MessageDeliveryAttempt.objects.select_for_update()
        .select_related("channel", "channel__connection")
        .filter(id=attempt_id, organization=message.organization, message=message)
        .first()
    )
    if attempt is None or attempt.status not in {
        MessageDeliveryAttempt.Status.REQUESTED,
        MessageDeliveryAttempt.Status.SENDING,
    }:
        raise InvalidMessage("Tentativa não está aguardando envio.")
    now = timezone.now()
    if attempt.dispatch_available_at and attempt.dispatch_available_at > now:
        raise InvalidMessage("Tentativa ainda está em espera controlada.")
    if attempt.dispatch_lease_expires_at and attempt.dispatch_lease_expires_at > now:
        raise InvalidMessage("Tentativa já está reservada para envio.")
    if attempt.status == MessageDeliveryAttempt.Status.SENDING:
        attempt.status = MessageDeliveryAttempt.Status.UNCERTAIN
        attempt.dispatch_lease_token = None
        attempt.dispatch_lease_expires_at = None
        attempt.dispatch_available_at = None
        attempt.dispatch_error_code = "worker_lost_after_send_started"
        attempt.version += 1
        attempt.save(
            update_fields=(
                "status",
                "dispatch_lease_token",
                "dispatch_lease_expires_at",
                "dispatch_available_at",
                "dispatch_error_code",
                "version",
                "updated_at",
            )
        )
        from_status = message.status
        message.status = Message.Status.UNCERTAIN
        message.version += 1
        message.save(update_fields=("status", "version", "updated_at"))
        command_id = f"{attempt.id}:lost"
        _history(
            message=message,
            from_status=from_status,
            actor=None,
            command_id=command_id,
            source="dispatch_worker",
            reason_code="worker_lost_after_send_started",
        )
        _audit(message=message, actor=None, action=MESSAGE_STATUS_CHANGED, payload={"has_delivery_ambiguity": True})
        _outbox(
            message=message,
            event_type=MESSAGE_STATUS_CHANGED,
            command_id=command_id,
            extra={"has_delivery_ambiguity": True},
        )
        return message, attempt
    if message.status == Message.Status.QUEUED:
        message.status = Message.Status.PENDING
    if message.status != Message.Status.PENDING:
        raise InvalidMessage("Message não está pendente de envio.")
    attempt.dispatch_lease_token = uuid.uuid4()
    attempt.dispatch_lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    attempt.dispatch_attempts += 1
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = ""
    attempt.save(
        update_fields=(
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_attempts",
            "dispatch_available_at",
            "dispatch_error_code",
            "updated_at",
        )
    )
    from_status = message.status
    message.status = Message.Status.QUEUED
    message.queued_at = now
    message.version += 1
    message.save(update_fields=("status", "queued_at", "version", "updated_at"))
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=f"{attempt.id}:{attempt.dispatch_attempts}",
        source="dispatch_worker",
    )
    return message, attempt


@transaction.atomic
def release_dispatch(*, attempt_id, lease_token, error_code=""):
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        return False
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        return False
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_error_code = error_code
    if attempt.status == MessageDeliveryAttempt.Status.SENDING:
        attempt.status = MessageDeliveryAttempt.Status.REQUESTED
        attempt.version += 1
    attempt.dispatch_available_at = (
        timezone.now()
        + timedelta(seconds=min(DISPATCH_RETRY_MAX_SECONDS, 5 * (2 ** min(attempt.dispatch_attempts, 6))))
        if error_code
        else None
    )
    attempt.save(
        update_fields=(
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_error_code",
            "dispatch_available_at",
            "status",
            "version",
            "updated_at",
        )
    )
    if message.status in {Message.Status.QUEUED, Message.Status.SENDING}:
        from_status = message.status
        message.status = Message.Status.PENDING
        message.version += 1
        message.save(update_fields=("status", "version", "updated_at"))
        _history(
            message=message,
            from_status=from_status,
            actor=None,
            command_id=f"{attempt.id}:release",
            source="dispatch_worker",
            reason_code=error_code,
        )
    return True


def _dispatch_error_code(exc):
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ProviderEffectsDisabled):
        return "external_effect_blocked"
    if isinstance(exc, (ConnectionError, OSError)):
        return "transport_error"
    return "provider_error"


def _resolve_active_checkout_link(*, organization, intent_id):
    intent = PaymentIntent.objects.select_for_update().filter(organization=organization, id=intent_id).first()
    if intent is None or intent.status != PaymentIntent.Status.AWAITING_PAYMENT:
        raise InvalidMessage("Link de checkout não está ativo para envio.")
    attempt = (
        PaymentAttempt.objects.select_for_update()
        .filter(intent=intent, status=PaymentAttempt.Status.ACTIVE, hosted_url__gt="")
        .first()
    )
    if attempt is None:
        raise InvalidMessage("Pagamento não possui link de checkout ativo.")
    if attempt.expires_at and attempt.expires_at <= timezone.now():
        raise InvalidMessage("Link de checkout expirado.")
    return attempt.hosted_url


def _render_context(*, message):
    parameters = dict(message.parameter_snapshot or {})
    if "checkout_link" in (message.template.parameter_schema or []):
        if message.source_type != Message.SourceType.PAYMENT or message.purpose != PURPOSE_CHECKOUT_LINK:
            raise InvalidMessage("checkout_link exige fonte de pagamento com link ativo.")
        parameters["checkout_link"] = _resolve_active_checkout_link(
            organization=message.organization,
            intent_id=message.source_id,
        )
    return parameters


def _revalidate_dispatch_contract(*, message):
    """Re-check every mutable dependency immediately before provider dispatch."""
    source, customer, _ = _resolve_source(
        organization=message.organization,
        source_type=message.source_type,
        source_id=message.source_id,
        purpose=message.purpose,
    )
    if customer.id != message.customer_id:
        raise InvalidMessage("Customer da fonte mudou; selecione explicitamente o registro canônico.")
    if source.version != message.source_version:
        raise InvalidMessage("Versão da fonte é incompatível com o snapshot da mensagem.")
    if message.customer.status != Customer.Status.ACTIVE or message.customer.merged_into_id is not None:
        raise InvalidMessage("Customer da mensagem não está elegível para envio.")
    if message.contact_point.customer_id != message.customer_id:
        raise OrganizationMismatch("ContactPoint não pertence ao Customer da mensagem.")
    if message.contact_point.normalized_value != message.destination_snapshot:
        raise InvalidMessage("Destino foi alterado; crie uma nova mensagem com o contato corrigido.")
    permission = _resolve_permission(
        organization=message.organization,
        customer=message.customer,
        contact_point=message.contact_point,
        channel_kind=message.channel_kind,
        purpose=message.purpose,
    )
    if permission.id != message.permission_evidence_id:
        raise InvalidMessage("Evidência de permissão mudou; crie uma nova mensagem.")
    if (
        message.template.version != message.template_version
        or message.template.semantic_key != message.template_semantic_key
    ):
        raise InvalidMessage("Versão do template não corresponde ao snapshot da mensagem.")
    _validate_template(
        organization=message.organization,
        template=message.template,
        channel_kind=message.channel_kind,
        purpose=message.purpose,
    )
    _validate_channel(
        organization=message.organization,
        channel=message.channel,
        channel_kind=message.channel_kind,
    )
    if message.channel.connection.organization_id != message.organization_id:
        raise OrganizationMismatch("Conexão do canal não pertence à organização.")
    if not message.channel.connection.is_active:
        raise InvalidMessage("Conexão do provider não está ativa.")
    if provider_channel_kind(message.channel.connection.provider) != message.channel_kind:
        raise InvalidMessage("Provider não é compatível com o canal da mensagem.")


@transaction.atomic
def build_send_request(*, message):
    message = _lock_message(organization=message.organization, message_id=message.id)
    return _build_send_request_locked(message=message)


def _build_send_request_locked(*, message):
    _revalidate_dispatch_contract(message=message)
    parameters = _render_context(message=message)
    text_body, html_body = render_message_body(template=message.template, parameters=parameters)
    if (
        message.channel.connection.provider == MessagingProviderConnection.Provider.WHATSAPP_CLOUD
        and not message.template.provider_template_reference
    ):
        raise InvalidMessage("WhatsApp Cloud exige referência de template oficial aprovado.")
    return SendRequest(
        destination=message.destination_snapshot,
        body=text_body,
        body_html=html_body,
        template_reference=message.template.provider_template_reference,
        provider_correlation_tag=message.attempts.get(dispatch_key=str(message.id)).provider_correlation_tag,
        channel_kind=message.channel_kind,
        provider=message.channel.connection.provider,
        locale=message.locale,
        template_parameters=tuple(str(parameters[key]) for key in message.template.parameter_schema),
    )


@transaction.atomic
def prepare_send_request(*, attempt_id, lease_token):
    """Linearize send authorization and request construction before provider I/O.

    The transaction locks the Message/attempt and all mutable eligibility
    dependencies while moving the attempt to ``sending``. Provider I/O starts
    only after this transaction commits, so a concurrent suppression/source or
    channel change either commits before this authorization and blocks it, or
    is ordered after the already-authorized send.
    """
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não encontrada.")
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidMessage("Lease de envio inválido.")
    if message.status != Message.Status.QUEUED or attempt.status != MessageDeliveryAttempt.Status.REQUESTED:
        raise InvalidMessage("Tentativa não está pronta para iniciar o envio.")

    # Lock each mutable eligibility record explicitly before the final check.
    message.customer = Customer.objects.select_for_update().get(
        id=message.customer_id,
        organization=message.organization,
    )
    message.contact_point = ContactPoint.objects.select_for_update().get(
        id=message.contact_point_id,
        customer_id=message.customer_id,
    )
    message.template = MessageTemplate.objects.select_for_update().get(
        id=message.template_id,
        organization=message.organization,
    )
    channel = (
        MessagingChannel.objects.select_for_update()
        .select_related("connection")
        .get(id=message.channel_id, organization=message.organization)
    )
    channel.connection = MessagingProviderConnection.objects.select_for_update().get(
        id=channel.connection_id,
        organization=message.organization,
    )
    message.channel = channel
    MessagingPreference.objects.select_for_update().filter(
        organization=message.organization,
        contact_point_id=message.contact_point_id,
        channel=message.channel_kind,
        purpose=message.purpose,
        is_active=True,
    ).first()

    attempt.status = MessageDeliveryAttempt.Status.SENDING
    attempt.version += 1
    attempt.save(update_fields=("status", "version", "updated_at"))
    from_status = message.status
    message.status = Message.Status.SENDING
    message.version += 1
    message.save(update_fields=("status", "version", "updated_at"))
    request = _build_send_request_locked(message=message)
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=f"{attempt.id}:sending",
        source="dispatch_worker",
    )
    return message, attempt, request


@transaction.atomic
def mark_sending(*, attempt_id, lease_token):
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não encontrada.")
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidMessage("Lease de envio inválido.")
    if message.status != Message.Status.QUEUED or attempt.status != MessageDeliveryAttempt.Status.REQUESTED:
        raise InvalidMessage("Tentativa não está pronta para iniciar o envio.")
    attempt.status = MessageDeliveryAttempt.Status.SENDING
    attempt.version += 1
    attempt.save(update_fields=("status", "version", "updated_at"))
    from_status = message.status
    message.status = Message.Status.SENDING
    message.version += 1
    message.save(update_fields=("status", "version", "updated_at"))
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=f"{attempt.id}:sending",
        source="dispatch_worker",
    )
    return message, attempt


@transaction.atomic
def apply_provider_acceptance(*, attempt_id, lease_token, result, idempotency_key):
    if not result.accepted:
        raise InvalidMessage("Provider não aceitou a mensagem.")
    if not result.external_message_id:
        raise InvalidMessage("Provider aceitou sem identificador de mensagem.")
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não encontrada.")
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidMessage("Lease de envio inválido.")
    if message.status != Message.Status.SENDING:
        raise InvalidMessage("Message não está em envio.")
    attempt.external_message_id = result.external_message_id
    attempt.status = MessageDeliveryAttempt.Status.ACCEPTED
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = ""
    attempt.version += 1
    try:
        attempt.save(
            update_fields=(
                "external_message_id",
                "status",
                "dispatch_lease_token",
                "dispatch_lease_expires_at",
                "dispatch_available_at",
                "dispatch_error_code",
                "version",
                "updated_at",
            )
        )
    except IntegrityError as exc:
        raise InvalidMessage("Identificador externo duplicado.") from exc
    from_status = message.status
    message.status = Message.Status.SENT
    message.sent_at = timezone.now()
    message.version += 1
    message.save(update_fields=("status", "sent_at", "version", "updated_at"))
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=idempotency_key,
        source="provider_worker",
    )
    _audit(message=message, actor=None, action=MESSAGE_STATUS_CHANGED)
    _outbox(message=message, event_type=MESSAGE_STATUS_CHANGED, command_id=idempotency_key)
    return message


@transaction.atomic
def mark_uncertain(*, attempt_id, lease_token, idempotency_key):
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não encontrada.")
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidMessage("Lease de envio inválido.")
    attempt.status = MessageDeliveryAttempt.Status.UNCERTAIN
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = "timeout"
    attempt.version += 1
    attempt.save(
        update_fields=(
            "status",
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_available_at",
            "dispatch_error_code",
            "version",
            "updated_at",
        )
    )
    from_status = message.status
    message.status = Message.Status.UNCERTAIN
    message.version += 1
    message.save(update_fields=("status", "version", "updated_at"))
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=idempotency_key,
        source="provider_worker",
        reason_code="timeout_after_possible_acceptance",
    )
    _audit(message=message, actor=None, action=MESSAGE_STATUS_CHANGED, payload={"has_delivery_ambiguity": True})
    _outbox(
        message=message,
        event_type=MESSAGE_STATUS_CHANGED,
        command_id=idempotency_key,
        extra={"has_delivery_ambiguity": True},
    )
    return message


def dispatch_message(*, attempt, adapter, idempotency_key):
    message, attempt = claim_dispatch(attempt_id=attempt.id)
    if message.status == Message.Status.UNCERTAIN:
        return message
    if adapter.provider != message.channel.connection.provider:
        release_dispatch(attempt_id=attempt.id, lease_token=attempt.dispatch_lease_token, error_code="provider_error")
        raise InvalidMessage("Adapter não corresponde ao provider do canal.")
    assert_capability(adapter.provider, "send_text")
    try:
        message, attempt, request = prepare_send_request(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
        )
    except MessagingDomainError:
        return mark_failed(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            idempotency_key=idempotency_key,
            reason_code="source_not_fresh",
        )
    try:
        if getattr(adapter, "external", True):
            require_network_allowed()
        result = adapter.send_text(request)
        if not result.accepted:
            return mark_failed(
                attempt_id=attempt.id,
                lease_token=attempt.dispatch_lease_token,
                idempotency_key=idempotency_key,
                reason_code="provider_rejected",
            )
        return apply_provider_acceptance(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            result=result,
            idempotency_key=idempotency_key,
        )
    except (TimeoutError, ConnectionError, OSError):
        return mark_uncertain(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            idempotency_key=idempotency_key,
        )
    except ProviderEffectsDisabled as exc:
        release_dispatch(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code=_dispatch_error_code(exc),
        )
        raise
    except Exception:
        return mark_uncertain(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            idempotency_key=idempotency_key,
        )


@transaction.atomic
def mark_failed(*, attempt_id, lease_token, idempotency_key, reason_code=""):
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não encontrada.")
    message = _lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidMessage("Lease de envio inválido.")
    attempt.status = MessageDeliveryAttempt.Status.FAILED
    attempt.dispatch_lease_token = None
    attempt.dispatch_lease_expires_at = None
    attempt.dispatch_available_at = None
    attempt.dispatch_error_code = reason_code
    attempt.version += 1
    attempt.save(
        update_fields=(
            "status",
            "dispatch_lease_token",
            "dispatch_lease_expires_at",
            "dispatch_available_at",
            "dispatch_error_code",
            "version",
            "updated_at",
        )
    )
    from_status = message.status
    message.status = Message.Status.FAILED
    message.failed_at = timezone.now()
    message.version += 1
    message.save(update_fields=("status", "failed_at", "version", "updated_at"))
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=idempotency_key,
        source="provider_worker",
        reason_code=reason_code,
    )
    _audit(message=message, actor=None, action=MESSAGE_STATUS_CHANGED, payload={"has_delivery_ambiguity": False})
    _outbox(
        message=message,
        event_type=MESSAGE_STATUS_CHANGED,
        command_id=idempotency_key,
    )
    return message


def _apply_canonical_evidence(*, message, attempt, target, command_id, source, reason_code=""):
    if message.status in TERMINAL_MESSAGE_STATUSES:
        reason = (
            "late_failure_evidence"
            if (message.status == Message.Status.DELIVERED and target == Message.Status.FAILED)
            else "non_monotonic_evidence"
        )
        return False, reason
    if target == message.status:
        return False, ""
    from_status = message.status
    attempt.status = {
        Message.Status.SENT: MessageDeliveryAttempt.Status.ACCEPTED,
        Message.Status.DELIVERED: MessageDeliveryAttempt.Status.DELIVERED,
        Message.Status.FAILED: MessageDeliveryAttempt.Status.FAILED,
    }.get(target, attempt.status)
    message.status = target
    now = timezone.now()
    if target == Message.Status.DELIVERED:
        message.delivered_at = now
    elif target == Message.Status.FAILED:
        message.failed_at = now
    message.version += 1
    attempt.version += 1
    message.save(
        update_fields=(
            "status",
            "delivered_at",
            "failed_at",
            "version",
            "updated_at",
        )
    )
    attempt.save(update_fields=("status", "version", "updated_at"))
    _history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=command_id,
        source=source,
        reason_code=reason_code,
    )
    return True, reason_code


@transaction.atomic
def apply_delivery_evidence(
    *,
    channel,
    connection,
    external_event_id,
    external_message_id,
    provider_status,
    authenticated_request_id_digest,
    request_digest,
):
    organization = channel.organization
    scoped_channel = MessagingChannel.objects.filter(
        organization=organization,
        id=channel.id,
        connection=connection,
    ).first()
    if scoped_channel is None:
        raise OrganizationMismatch("Canal não pertence à conexão configurada.")
    if not connection.is_active or not connection.callbacks_enabled:
        raise InvalidMessage("Callback não está habilitado para esta conexão.")
    existing = MessageWebhookReceipt.objects.filter(
        channel=scoped_channel,
        external_message_id=external_message_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
    ).first()
    if existing:
        return existing
    target = map_delivery_status(provider=connection.provider, status=provider_status)
    attempt = (
        MessageDeliveryAttempt.objects.select_for_update()
        .filter(channel=scoped_channel, external_message_id=external_message_id)
        .first()
    )
    if attempt is None:
        raise OrganizationMismatch("Mensagem externa não pertence ao canal configurado.")
    message = _lock_message(organization=organization, message_id=attempt.message_id)
    attempt = MessageDeliveryAttempt.objects.select_for_update().get(id=attempt.id, message=message)
    existing = MessageWebhookReceipt.objects.filter(
        channel=scoped_channel,
        external_message_id=external_message_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
    ).first()
    if existing:
        return existing
    command_id = hashlib.sha256(f"{connection.id}:{external_event_id}".encode()).hexdigest()
    changed, reason_code = _apply_canonical_evidence(
        message=message,
        attempt=attempt,
        target=target,
        command_id=command_id,
        source="provider_callback",
        reason_code="",
    )
    if changed or reason_code:
        _audit(
            message=message,
            actor=None,
            action=MESSAGE_STATUS_CHANGED,
            payload={"has_delivery_inconsistency": bool(reason_code)},
        )
        _outbox(
            message=message,
            event_type=MESSAGE_STATUS_CHANGED,
            command_id=command_id,
            extra={"has_delivery_inconsistency": bool(reason_code)},
        )
    if target == Message.Status.FAILED and provider_status in HARD_FEEDBACK_STATUSES:
        _record_hard_feedback_suppression(message=message)
    receipt = MessageWebhookReceipt.objects.create(
        organization=organization,
        connection=connection,
        channel=scoped_channel,
        external_event_id=external_event_id,
        external_message_id=external_message_id,
        authenticated_request_id_digest=authenticated_request_id_digest,
        request_digest=request_digest,
        canonical_result=message.status,
        has_inconsistency=bool(reason_code),
        reason_code=reason_code,
        accepted=True,
    )
    return receipt


def _record_hard_feedback_suppression(*, message):
    MessagingPreference.objects.filter(
        organization=message.organization,
        contact_point=message.contact_point,
        channel=message.channel_kind,
        purpose=message.purpose,
        is_active=True,
    ).update(is_active=False)
    MessagingPreference.objects.create(
        organization=message.organization,
        contact_point=message.contact_point,
        channel=message.channel_kind,
        purpose=message.purpose,
        decision=MessagingPreference.Decision.SUPPRESSED,
        provenance="provider_hard_feedback",
        policy_version=message.permission_policy_version or 1,
        effective_at=timezone.now(),
        is_active=True,
    )


@transaction.atomic
def cancel_message(*, organization, actor, message, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"message_id": str(message.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="cancel_message",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_message(receipt)
    message = _lock_message(organization=organization, message_id=message.id)
    _ensure_version(obj=message, expected_version=expected_version)
    if message.status not in {Message.Status.PENDING, Message.Status.QUEUED}:
        raise InvalidMessage("Message não pode ser cancelada neste estado.")
    attempt = (
        MessageDeliveryAttempt.objects.select_for_update()
        .filter(message=message, status=MessageDeliveryAttempt.Status.REQUESTED)
        .first()
    )
    if attempt is not None:
        attempt.status = MessageDeliveryAttempt.Status.CANCELLED
        attempt.dispatch_lease_token = None
        attempt.dispatch_lease_expires_at = None
        attempt.dispatch_available_at = None
        attempt.version += 1
        attempt.save(
            update_fields=(
                "status",
                "dispatch_lease_token",
                "dispatch_lease_expires_at",
                "dispatch_available_at",
                "version",
                "updated_at",
            )
        )
    from_status = message.status
    message.status = Message.Status.CANCELLED
    message.cancelled_at = timezone.now()
    message.version += 1
    message.save(update_fields=("status", "cancelled_at", "version", "updated_at"))
    _history(message=message, from_status=from_status, actor=actor, command_id=idempotency_key, source="command")
    _audit(message=message, actor=actor, action=MESSAGE_STATUS_CHANGED)
    _outbox(message=message, event_type=MESSAGE_STATUS_CHANGED, command_id=idempotency_key)
    complete_command(receipt=receipt, message=message, attempt=attempt)
    return message


def reconcile_uncertain(*, organization, actor, message, expected_version, idempotency_key, adapter):
    _require_manager(actor=actor, organization=organization)
    scoped = Message.objects.filter(organization=organization, id=message.id).first()
    if scoped is None:
        raise OrganizationMismatch("Message não pertence à organização.")
    if scoped.status != Message.Status.UNCERTAIN:
        raise InvalidMessage("Somente mensagem incerta pode ser reconciliada.")
    attempt = (
        MessageDeliveryAttempt.objects.select_related("channel", "channel__connection")
        .filter(message=scoped, external_message_id__gt="")
        .order_by("-created_at")
        .first()
    )
    if attempt is None:
        raise InvalidMessage("Mensagem incerta não possui identificador externo para consulta.")
    if adapter.provider != attempt.channel.connection.provider:
        raise InvalidMessage("Adapter não corresponde ao provider.")
    assert_capability(adapter.provider, "message_status_query")
    if getattr(adapter, "external", True):
        require_network_allowed()
    provider_status = adapter.fetch_status(attempt.external_message_id)
    target = map_delivery_status(provider=adapter.provider, status=provider_status)
    return _apply_reconciliation(
        organization=organization,
        actor=actor,
        message_id=message.id,
        attempt_id=attempt.id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        target=target,
    )


@transaction.atomic
def _apply_reconciliation(*, organization, actor, message_id, attempt_id, expected_version, idempotency_key, target):
    payload = {"message_id": str(message_id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="reconcile_uncertain",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_message(receipt)
    message = _lock_message(organization=organization, message_id=message_id)
    _ensure_version(obj=message, expected_version=expected_version)
    if message.status != Message.Status.UNCERTAIN:
        raise InvalidMessage("Somente mensagem incerta pode ser reconciliada.")
    attempt = MessageDeliveryAttempt.objects.select_for_update().get(id=attempt_id, message=message)
    command_id = idempotency_key
    changed, reason_code = _apply_canonical_evidence(
        message=message,
        attempt=attempt,
        target=target,
        command_id=command_id,
        source="reconciliation",
        reason_code="",
    )
    if changed:
        _audit(
            message=message,
            actor=actor,
            action=MESSAGE_STATUS_CHANGED,
            payload={"has_delivery_inconsistency": bool(reason_code)},
        )
        _outbox(
            message=message,
            event_type=MESSAGE_STATUS_CHANGED,
            command_id=command_id,
            extra={"has_delivery_inconsistency": bool(reason_code)},
        )
    complete_command(receipt=receipt, message=message, attempt=attempt)
    return message


@transaction.atomic
def create_provider_connection(*, organization, actor, provider, mode, display_name, credential_alias, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    validate_provider_mode(provider=provider, mode=mode)
    payload = {
        "provider": provider,
        "mode": mode,
        "display_name": display_name,
        "credential_alias": credential_alias,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_provider_connection",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        connection = MessagingProviderConnection.objects.filter(
            organization=organization,
            provider=provider,
            display_name=display_name,
        ).first()
        if connection is None:
            raise IdempotencyConflict("Conexão resultante não existe.")
        return connection
    connection = MessagingProviderConnection.objects.create(
        organization=organization,
        provider=provider,
        mode=mode,
        display_name=display_name,
        credential_alias=credential_alias,
        capability_snapshot=sorted(provider_capabilities(provider)),
    )
    record_event(
        organization=organization,
        actor=actor,
        action="messaging.connection_created",
        entity_type="messaging_provider_connection",
        entity_id=connection.id,
        payload={"provider": connection.provider, "mode": connection.mode, "version": connection.version},
    )
    complete_command(receipt=receipt, message=None)
    return connection


@transaction.atomic
def set_provider_connection_active(*, organization, actor, connection, expected_version, is_active, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    operation = "activate_provider_connection" if is_active else "disable_provider_connection"
    payload = {
        "connection_id": str(connection.id),
        "expected_version": expected_version,
        "is_active": is_active,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation=operation,
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        existing = MessagingProviderConnection.objects.filter(
            organization=organization,
            id=connection.id,
        ).first()
        if existing is None:
            raise IdempotencyConflict("Conexão resultante não existe.")
        return existing
    scoped = (
        MessagingProviderConnection.objects.select_for_update()
        .filter(
            organization=organization,
            id=connection.id,
        )
        .first()
    )
    if scoped is None:
        raise OrganizationMismatch("Conexão não pertence à organização.")
    _ensure_version(obj=scoped, expected_version=expected_version)
    if scoped.is_active == is_active:
        raise InvalidMessage("Conexão já está no estado solicitado.")
    scoped.is_active = is_active
    if not is_active:
        scoped.callbacks_enabled = False
    scoped.version += 1
    scoped.save(update_fields=("is_active", "callbacks_enabled", "version", "updated_at"))
    record_event(
        organization=organization,
        actor=actor,
        action=f"messaging.connection_{'activated' if is_active else 'disabled'}",
        entity_type="messaging_provider_connection",
        entity_id=scoped.id,
        payload={"provider": scoped.provider, "is_active": scoped.is_active, "version": scoped.version},
    )
    complete_command(receipt=receipt, message=None)
    return scoped


@transaction.atomic
def create_channel(
    *,
    organization,
    actor,
    connection,
    kind,
    display_name,
    credential_alias,
    idempotency_key,
):
    _require_manager(actor=actor, organization=organization)
    if connection.organization_id != organization.id:
        raise OrganizationMismatch("Conexão não pertence à organização.")
    if not connection.is_active:
        raise InvalidMessage("Conexão deve estar ativa para criar canal.")
    payload = {
        "connection_id": str(connection.id),
        "kind": kind,
        "display_name": display_name,
        "credential_alias": credential_alias,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_channel",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        channel = MessagingChannel.objects.filter(
            organization=organization,
            connection=connection,
            kind=kind,
            display_name=display_name,
        ).first()
        if channel is None:
            raise IdempotencyConflict("Canal resultante não existe.")
        return channel
    if kind != provider_channel_kind(connection.provider):
        raise InvalidMessage("Tipo de canal incompatível com a conexão.")
    external_channel_id = ""
    state = MessagingChannel.State.INACTIVE
    if connection.provider == MessagingProviderConnection.Provider.EVOLUTION:
        state = MessagingChannel.State.PAIRING_REQUIRED
    channel = MessagingChannel.objects.create(
        organization=organization,
        connection=connection,
        kind=kind,
        display_name=display_name,
        credential_alias=credential_alias,
        external_channel_id=external_channel_id,
        capability_snapshot=sorted(provider_capabilities(connection.provider)),
        state=state,
    )
    if connection.provider == MessagingProviderConnection.Provider.EVOLUTION:
        channel.external_channel_id = evolution_instance_name(
            organization_id=organization.id,
            channel_id=channel.id,
        )
        channel.save(update_fields=("external_channel_id", "updated_at"))
    complete_command(receipt=receipt, message=None)
    return channel


@transaction.atomic
def request_pairing(*, organization, actor, channel, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    scoped = (
        MessagingChannel.objects.filter(organization=organization, id=channel.id).select_related("connection").first()
    )
    if scoped is None:
        raise OrganizationMismatch("Canal não pertence à organização.")
    if scoped.connection.provider != MessagingProviderConnection.Provider.EVOLUTION:
        raise InvalidMessage("Somente canal Evolution pode solicitar pareamento.")
    assert_capability(scoped.connection.provider, "linked_device_pairing")
    _ensure_version(obj=scoped, expected_version=expected_version)
    if not scoped.connection.is_active:
        raise InvalidMessage("Conexão do provider não está ativa.")
    require_network_allowed()
    raise ProviderEffectsDisabled("QR e pairing code são efêmeros; efeitos externos de Messaging estão desabilitados.")


@transaction.atomic
def activate_channel(*, organization, actor, channel, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"channel_id": str(channel.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="activate_channel",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return MessagingChannel.objects.filter(organization=organization, id=channel.id).first()
    scoped = (
        MessagingChannel.objects.select_for_update()
        .select_related("connection")
        .filter(organization=organization, id=channel.id)
        .first()
    )
    if scoped is None:
        raise OrganizationMismatch("Canal não pertence à organização.")
    _ensure_version(obj=scoped, expected_version=expected_version)
    if not scoped.connection.is_active:
        raise InvalidMessage("Conexão do provider não está ativa.")
    if scoped.connection.provider == MessagingProviderConnection.Provider.EVOLUTION:
        raise ProviderEffectsDisabled("Evolution só pode ser ativada após pareamento externo confirmado.")
    if scoped.state in {MessagingChannel.State.ACTIVE, MessagingChannel.State.DISABLED}:
        raise InvalidMessage("Canal não pode ser ativado a partir deste estado.")
    from_state = scoped.state
    scoped.state = MessagingChannel.State.ACTIVE
    scoped.version += 1
    scoped.save(update_fields=("state", "version", "updated_at"))
    record_event(
        organization=organization,
        actor=actor,
        action="messaging.channel_activated",
        entity_type="messaging_channel",
        entity_id=scoped.id,
        payload={"from_state": from_state, "state": scoped.state, "version": scoped.version},
    )
    complete_command(receipt=receipt, message=None)
    return scoped


@transaction.atomic
def disable_channel(*, organization, actor, channel, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"channel_id": str(channel.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="disable_channel",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return MessagingChannel.objects.filter(organization=organization, id=channel.id).first()
    scoped = MessagingChannel.objects.select_for_update().filter(organization=organization, id=channel.id).first()
    if scoped is None:
        raise OrganizationMismatch("Canal não pertence à organização.")
    _ensure_version(obj=scoped, expected_version=expected_version)
    scoped.state = MessagingChannel.State.DISABLED
    scoped.version += 1
    scoped.save(update_fields=("state", "version", "updated_at"))
    complete_command(receipt=receipt, message=None)
    return scoped


@transaction.atomic
def create_template(
    *,
    organization,
    actor,
    semantic_key,
    name,
    channel,
    locale,
    body_text,
    body_html,
    parameter_schema,
    provider_template_reference,
    idempotency_key,
):
    _require_manager(actor=actor, organization=organization)
    schema = validate_parameter_schema(parameter_schema)
    from apps.messaging.content import placeholders

    expected = placeholders(body_text) | placeholders(body_html or "")
    if not expected.issubset(schema):
        raise InvalidMessage("Template referencia parâmetro fora do schema aprovado.")
    validate_transactional_template(
        semantic_key=semantic_key,
        channel=channel,
        locale=locale,
        body_text=body_text,
        body_html=body_html,
        parameter_schema=schema,
    )
    payload = {
        "semantic_key": semantic_key,
        "name": name,
        "channel": channel,
        "locale": locale,
        "body_text": body_text,
        "body_html": body_html,
        "parameter_schema": schema,
        "provider_template_reference": provider_template_reference,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="create_template",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        template = MessageTemplate.objects.filter(
            organization=organization,
            semantic_key=semantic_key,
            version=receipt.resulting_version,
        ).first()
        if template is None:
            raise IdempotencyConflict("Template resultante não existe.")
        return template
    latest = (
        MessageTemplate.objects.select_for_update()
        .filter(organization=organization, semantic_key=semantic_key)
        .order_by("-version")
        .first()
    )
    next_version = 1 if latest is None else latest.version + 1
    template = MessageTemplate.objects.create(
        organization=organization,
        semantic_key=semantic_key,
        name=name,
        channel=channel,
        locale=locale,
        version=next_version,
        body_text=body_text,
        body_html=body_html,
        parameter_schema=schema,
        provider_template_reference=provider_template_reference,
    )
    complete_command(receipt=receipt, message=None, resulting_version=template.version)
    return template


@transaction.atomic
def deactivate_template(*, organization, actor, template, expected_version, idempotency_key):
    _require_manager(actor=actor, organization=organization)
    payload = {"template_id": str(template.id), "expected_version": expected_version}
    receipt, is_new = claim_command(
        organization=organization,
        operation="deactivate_template",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return MessageTemplate.objects.filter(organization=organization, id=template.id).first()
    scoped = MessageTemplate.objects.select_for_update().filter(organization=organization, id=template.id).first()
    if scoped is None:
        raise OrganizationMismatch("Template não pertence à organização.")
    _ensure_version(obj=scoped, expected_version=expected_version)
    if Message.objects.filter(template=scoped).exists():
        raise InvalidMessage("Template já usado é imutável.")
    scoped.is_active = False
    scoped.save(update_fields=("is_active", "updated_at"))
    complete_command(receipt=receipt, message=None)
    return scoped


@transaction.atomic
def record_preference(
    *,
    organization,
    actor,
    contact_point,
    channel,
    purpose,
    decision,
    provenance,
    policy_version,
    idempotency_key,
):
    _require_manager(actor=actor, organization=organization)
    if purpose not in PURPOSES:
        raise InvalidMessage("Finalidade de preferência inválida.")
    if contact_point.customer.organization_id != organization.id:
        raise OrganizationMismatch("ContactPoint não pertence à organização.")
    payload = {
        "contact_point_id": str(contact_point.id),
        "channel": channel,
        "purpose": purpose,
        "decision": decision,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="record_preference",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        preference = (
            MessagingPreference.objects.filter(
                organization=organization,
                contact_point=contact_point,
                channel=channel,
                purpose=purpose,
                decision=decision,
                is_active=True,
            )
            .order_by("-effective_at", "-created_at")
            .first()
        )
        if preference is None:
            raise IdempotencyConflict("Preferência resultante não existe.")
        return preference
    MessagingPreference.objects.filter(
        organization=organization,
        contact_point=contact_point,
        channel=channel,
        purpose=purpose,
        is_active=True,
    ).update(is_active=False)
    preference = MessagingPreference.objects.create(
        organization=organization,
        contact_point=contact_point,
        channel=channel,
        purpose=purpose,
        decision=decision,
        provenance=provenance,
        policy_version=policy_version,
        effective_at=timezone.now(),
        is_active=True,
    )
    complete_command(receipt=receipt, message=None)
    return preference


@transaction.atomic
def upsert_automation_rule(
    *,
    organization,
    actor,
    event_type,
    event_version=1,
    template,
    channel,
    purpose,
    is_enabled,
    idempotency_key,
    expected_version=None,
):
    _require_manager(actor=actor, organization=organization)
    if event_type not in ALLOWLISTED_SOURCE_EVENTS:
        raise InvalidMessage("Evento fora do allowlist de automação.")
    if (
        isinstance(event_version, bool)
        or not isinstance(event_version, int)
        or event_version != SOURCE_EVENT_CONTRACT_VERSIONS[event_type]
    ):
        raise InvalidMessage("Versão do contrato do evento não está aprovada.")
    if purpose != EVENT_PURPOSES[event_type]:
        raise InvalidMessage("Finalidade incompatível com o evento.")
    if template.organization_id != organization.id or channel.organization_id != organization.id:
        raise OrganizationMismatch("Template ou canal não pertence à organização.")
    if template.channel != channel.kind:
        raise InvalidMessage("Template incompatível com o canal da regra.")
    _validate_template(
        organization=organization,
        template=template,
        channel_kind=channel.kind,
        purpose=purpose,
    )
    payload = {
        "event_type": event_type,
        "event_version": event_version,
        "template_id": str(template.id),
        "channel_id": str(channel.id),
        "purpose": purpose,
        "is_enabled": is_enabled,
        "expected_version": expected_version,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="upsert_automation_rule",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        rule = MessageAutomationRule.objects.filter(
            organization=organization,
            event_type=event_type,
            event_version=event_version,
            template=template,
            channel=channel,
        ).first()
        if rule is None:
            raise IdempotencyConflict("Regra resultante não existe.")
        return rule
    # Locking the template serializes creation of the same natural rule and
    # avoids a first-write race before the unique constraint is reached.
    MessageTemplate.objects.select_for_update().get(organization=organization, id=template.id)
    rule = MessageAutomationRule.objects.select_for_update().filter(
        organization=organization,
        event_type=event_type,
        template=template,
        channel=channel,
    ).first()
    if rule is None:
        if expected_version is not None:
            raise VersionConflict("Regra ainda não existe; versão esperada deve ser omitida.")
        rule = MessageAutomationRule.objects.create(
            organization=organization,
            event_type=event_type,
            event_version=event_version,
            template=template,
            channel=channel,
            purpose=purpose,
            is_enabled=is_enabled,
            version=1,
        )
    else:
        if expected_version is None:
            raise VersionConflict("Versão esperada é obrigatória para atualizar a regra.")
        _ensure_version(obj=rule, expected_version=expected_version)
        rule.purpose = purpose
        rule.event_version = event_version
        rule.is_enabled = is_enabled
        rule.version += 1
        rule.save(update_fields=("event_version", "purpose", "is_enabled", "version", "updated_at"))
    complete_command(receipt=receipt, message=None, resulting_version=rule.version)
    return rule
