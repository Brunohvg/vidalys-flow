from django.db import transaction

from apps.customers.models import ContactPoint, Customer
from apps.fulfillment.models import Fulfillment
from apps.messaging import policies, services
from apps.messaging.content import render_message_body
from apps.messaging.exceptions import InvalidMessage, MessagingPermissionDenied, OrganizationMismatch, ProviderEffectsDisabled
from apps.messaging.models import Message, MessageDeliveryAttempt, MessageTemplate, MessagingChannel, MessagingPreference, MessagingProviderConnection
from apps.messaging.providers import SendRequest, assert_capability, provider_channel_kind, require_network_allowed
from apps.payments import policies as payment_policies
from apps.payments.models import PaymentIntent, PixPaymentInstruction

PURPOSE_PIX_INSTRUCTION = "pix_instruction"
TRACKING_TEMPLATE_KEY = "fulfillment_tracking"
PIX_TEMPLATE_KEY = "pix_instruction"


def _template(*, organization, channel, semantic_key):
    template = (
        MessageTemplate.objects.filter(
            organization=organization,
            semantic_key=semantic_key,
            channel=channel.kind,
            is_active=True,
        )
        .order_by("-version")
        .first()
    )
    if template is None:
        raise InvalidMessage("Template transacional aprovado não está configurado para este canal.")
    return template


def _require_manual_send(*, actor, organization):
    if not policies.can_request_manual_send(user=actor, organization=organization):
        raise MessagingPermissionDenied("Membership ativa é obrigatória para solicitar envio.")


@transaction.atomic
def create_tracking_message(
    *, organization, actor, fulfillment, channel, contact_point, idempotency_key
):
    _require_manual_send(actor=actor, organization=organization)
    source = (
        Fulfillment.objects.select_for_update()
        .select_related("order__customer")
        .filter(organization=organization, id=fulfillment.id)
        .first()
    )
    if source is None:
        raise OrganizationMismatch("Fulfillment não pertence à organização.")
    if source.method != Fulfillment.Method.DELIVERY:
        raise InvalidMessage("Rastreio só pode ser comunicado para entrega.")
    if source.status not in {Fulfillment.Status.READY, Fulfillment.Status.IN_TRANSIT}:
        raise InvalidMessage("Entrega não está em estado elegível para comunicar rastreio.")
    if not source.tracking_code and not source.tracking_url:
        raise InvalidMessage("Configure o rastreio antes de enviá-lo ao cliente.")
    customer = source.order.customer
    template = _template(
        organization=organization,
        channel=channel,
        semantic_key=TRACKING_TEMPLATE_KEY,
    )
    permission = services._resolve_permission(
        organization=organization,
        customer=customer,
        contact_point=contact_point,
        channel_kind=channel.kind,
        purpose=services.PURPOSE_FULFILLMENT_PROGRESS,
    )
    return services._create_message(
        organization=organization,
        source_type=Message.SourceType.FULFILLMENT,
        source_id=source.id,
        source_version=source.version,
        source_event_id=None,
        purpose=services.PURPOSE_FULFILLMENT_PROGRESS,
        template=template,
        channel=channel,
        customer=customer,
        contact_point=contact_point,
        permission=permission,
        parameters={
            "customer_name": customer.display_name,
            "order_number": source.order.display_number,
            "tracking_code": source.tracking_code or "—",
            "tracking_url": source.tracking_url or "—",
        },
        actor=actor,
        idempotency_key=idempotency_key,
        operation="create_tracking_message",
    )


@transaction.atomic
def create_pix_message(*, organization, actor, intent, channel, contact_point, idempotency_key):
    if not payment_policies.can_operate_payments(user=actor, organization=organization):
        raise MessagingPermissionDenied("Envio de instrução PIX exige papel de gerência em Payments.")
    source = (
        PaymentIntent.objects.select_for_update()
        .select_related("order__customer")
        .filter(organization=organization, id=intent.id)
        .first()
    )
    if source is None:
        raise OrganizationMismatch("Pagamento não pertence à organização.")
    if source.status not in {PaymentIntent.Status.PENDING, PaymentIntent.Status.AWAITING_PAYMENT}:
        raise InvalidMessage("Pagamento não está elegível para receber instruções PIX.")
    pix = PixPaymentInstruction.objects.select_for_update().filter(
        organization=organization,
        is_active=True,
    ).first()
    if pix is None:
        raise InvalidMessage("A Organization não possui instrução PIX ativa.")
    customer = source.order.customer
    template = _template(organization=organization, channel=channel, semantic_key=PIX_TEMPLATE_KEY)
    permission = services._resolve_permission(
        organization=organization,
        customer=customer,
        contact_point=contact_point,
        channel_kind=channel.kind,
        purpose=PURPOSE_PIX_INSTRUCTION,
    )
    return services._create_message(
        organization=organization,
        source_type=Message.SourceType.PAYMENT,
        source_id=source.id,
        source_version=source.version,
        source_event_id=None,
        purpose=PURPOSE_PIX_INSTRUCTION,
        template=template,
        channel=channel,
        customer=customer,
        contact_point=contact_point,
        permission=permission,
        parameters={
            "customer_name": source.customer_name_snapshot or customer.display_name,
            "order_number": source.order_number_snapshot,
            "pix_key_type": pix.get_key_type_display(),
            "pix_key": pix.key_value,
            "pix_beneficiary": pix.beneficiary_name,
            "pix_bank": pix.bank_name or "não informado",
        },
        actor=actor,
        idempotency_key=idempotency_key,
        operation="create_pix_message",
    )


def _validate_pix_source(*, message):
    intent = (
        PaymentIntent.objects.select_for_update()
        .select_related("order__customer")
        .filter(organization=message.organization, id=message.source_id)
        .first()
    )
    if intent is None or intent.status not in {PaymentIntent.Status.PENDING, PaymentIntent.Status.AWAITING_PAYMENT}:
        raise InvalidMessage("Pagamento deixou de ser elegível para instrução PIX.")
    if intent.version != message.source_version or intent.order.customer_id != message.customer_id:
        raise InvalidMessage("Fonte da instrução PIX mudou; crie uma nova mensagem.")
    pix = PixPaymentInstruction.objects.select_for_update().filter(
        organization=message.organization,
        is_active=True,
    ).first()
    if pix is None:
        raise InvalidMessage("Instrução PIX deixou de estar ativa.")
    current = {
        "customer_name": intent.customer_name_snapshot or intent.order.customer.display_name,
        "order_number": intent.order_number_snapshot,
        "pix_key_type": pix.get_key_type_display(),
        "pix_key": pix.key_value,
        "pix_beneficiary": pix.beneficiary_name,
        "pix_bank": pix.bank_name or "não informado",
    }
    if current != (message.parameter_snapshot or {}):
        raise InvalidMessage("Configuração PIX mudou; crie uma nova mensagem antes do envio.")
    return current


@transaction.atomic
def prepare_pix_send_request(*, attempt_id, lease_token):
    ref = MessageDeliveryAttempt.objects.filter(id=attempt_id).values("organization_id", "message_id").first()
    if ref is None:
        raise InvalidMessage("Tentativa não encontrada.")
    message = services._lock_message(organization=ref["organization_id"], message_id=ref["message_id"])
    attempt = MessageDeliveryAttempt.objects.select_for_update().filter(id=attempt_id, message=message).first()
    if attempt is None or attempt.dispatch_lease_token != lease_token:
        raise InvalidMessage("Lease de envio inválido.")
    if message.status != Message.Status.QUEUED or attempt.status != MessageDeliveryAttempt.Status.REQUESTED:
        raise InvalidMessage("Tentativa não está pronta para iniciar o envio.")
    if message.purpose != PURPOSE_PIX_INSTRUCTION or message.source_type != Message.SourceType.PAYMENT:
        raise InvalidMessage("Mensagem não é uma instrução PIX contextual.")

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

    if message.customer.status != Customer.Status.ACTIVE or message.customer.merged_into_id is not None:
        raise InvalidMessage("Customer da mensagem não está elegível para envio.")
    if message.contact_point.normalized_value != message.destination_snapshot:
        raise InvalidMessage("Destino foi alterado; crie uma nova mensagem.")
    permission = services._resolve_permission(
        organization=message.organization,
        customer=message.customer,
        contact_point=message.contact_point,
        channel_kind=message.channel_kind,
        purpose=message.purpose,
    )
    if permission.id != message.permission_evidence_id:
        raise InvalidMessage("Evidência de permissão mudou; crie uma nova mensagem.")
    if message.template.version != message.template_version or message.template.semantic_key != PIX_TEMPLATE_KEY:
        raise InvalidMessage("Template PIX mudou; crie uma nova mensagem.")
    services._validate_template(
        organization=message.organization,
        template=message.template,
        channel_kind=message.channel_kind,
        purpose=message.purpose,
    )
    services._validate_channel(
        organization=message.organization,
        channel=message.channel,
        channel_kind=message.channel_kind,
    )
    if provider_channel_kind(message.channel.connection.provider) != message.channel_kind:
        raise InvalidMessage("Provider não é compatível com o canal da mensagem.")
    parameters = _validate_pix_source(message=message)
    text_body, html_body = render_message_body(template=message.template, parameters=parameters)
    if (
        message.channel.connection.provider == MessagingProviderConnection.Provider.WHATSAPP_CLOUD
        and not message.template.provider_template_reference
    ):
        raise InvalidMessage("WhatsApp Cloud exige referência de template oficial aprovado.")

    attempt.status = MessageDeliveryAttempt.Status.SENDING
    attempt.version += 1
    attempt.save(update_fields=("status", "version", "updated_at"))
    from_status = message.status
    message.status = Message.Status.SENDING
    message.version += 1
    message.save(update_fields=("status", "version", "updated_at"))
    services._history(
        message=message,
        from_status=from_status,
        actor=None,
        command_id=f"{attempt.id}:sending",
        source="dispatch_worker",
    )
    request = SendRequest(
        destination=message.destination_snapshot,
        body=text_body,
        body_html=html_body,
        template_reference=message.template.provider_template_reference,
        provider_correlation_tag=attempt.provider_correlation_tag,
        channel_kind=message.channel_kind,
        provider=message.channel.connection.provider,
        locale=message.locale,
        template_parameters=tuple(str(parameters[key]) for key in message.template.parameter_schema),
    )
    return message, attempt, request


def dispatch_pix_message(*, attempt, adapter, idempotency_key):
    message, attempt = services.claim_dispatch(attempt_id=attempt.id)
    if message.status == Message.Status.UNCERTAIN:
        return message
    if adapter.provider != message.channel.connection.provider:
        services.release_dispatch(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code="provider_error",
        )
        raise InvalidMessage("Adapter não corresponde ao provider do canal.")
    assert_capability(adapter.provider, "send_text")
    try:
        message, attempt, request = prepare_pix_send_request(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
        )
    except Exception as exc:
        if isinstance(exc, (InvalidMessage, OrganizationMismatch)):
            return services.mark_failed(
                attempt_id=attempt.id,
                lease_token=attempt.dispatch_lease_token,
                idempotency_key=idempotency_key,
                reason_code="source_not_fresh",
            )
        raise
    try:
        if getattr(adapter, "external", True):
            require_network_allowed()
        result = adapter.send_text(request)
        if not result.accepted:
            return services.mark_failed(
                attempt_id=attempt.id,
                lease_token=attempt.dispatch_lease_token,
                idempotency_key=idempotency_key,
                reason_code="provider_rejected",
            )
        return services.apply_provider_acceptance(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            result=result,
            idempotency_key=idempotency_key,
        )
    except (TimeoutError, ConnectionError, OSError):
        return services.mark_uncertain(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            idempotency_key=idempotency_key,
        )
    except ProviderEffectsDisabled as exc:
        services.release_dispatch(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            error_code=services._dispatch_error_code(exc),
        )
        raise
    except Exception:
        return services.mark_uncertain(
            attempt_id=attempt.id,
            lease_token=attempt.dispatch_lease_token,
            idempotency_key=idempotency_key,
        )
