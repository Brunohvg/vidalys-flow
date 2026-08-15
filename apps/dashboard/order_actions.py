from apps.fulfillment import policies as fulfillment_policies
from apps.fulfillment.models import Fulfillment
from apps.payments import policies as payment_policies
from apps.payments.models import PaymentIntent, PixPaymentInstruction


def _active_fulfillment(*, organization, order):
    return (
        Fulfillment.objects.filter(
            organization=organization,
            order__organization=organization,
            order=order,
        )
        .exclude(status__in=(Fulfillment.Status.COMPLETED, Fulfillment.Status.CANCELLED))
        .order_by("sequence")
        .first()
    )


def order_next_action(*, organization, order, user):
    """Return presentation-only next-action guidance from canonical domain state."""

    if order.organization_id != organization.id:
        return None

    if order.status == order.Status.DRAFT:
        return {
            "kind": "confirm_order",
            "title": "Pedido em rascunho",
            "description": "Revise os dados e confirme o pedido para iniciar cobrança e atendimento.",
        }
    if order.status == order.Status.CANCELLED:
        return {
            "kind": "closed",
            "title": "Pedido cancelado",
            "description": "Nenhuma ação operacional está disponível para este pedido.",
        }

    payment = PaymentIntent.objects.filter(
        organization=organization,
        order__organization=organization,
        order=order,
    ).first()
    can_operate_payment = payment_policies.can_operate_payments(user=user, organization=organization)

    if payment is None:
        return {
            "kind": "create_payment",
            "title": "Pagamento ainda não criado",
            "description": "Crie a cobrança integral para acompanhar o recebimento.",
            "can_operate": can_operate_payment,
        }

    if payment.status == PaymentIntent.Status.REQUIRES_ATTENTION:
        return {
            "kind": "payment_attention",
            "title": "Pagamento requer atenção",
            "description": "Resolva a divergência financeira antes de uma nova cobrança.",
            "payment": payment,
        }

    if payment.status not in {
        PaymentIntent.Status.PAID,
        PaymentIntent.Status.CANCELLED,
        PaymentIntent.Status.EXPIRED,
    }:
        pix = PixPaymentInstruction.objects.filter(
            organization=organization,
            is_active=True,
        ).first()
        return {
            "kind": "payment_pending",
            "title": "Pagamento pendente",
            "description": "Confirme um recebimento offline, use o PIX cadastrado ou gere um checkout hospedado.",
            "payment": payment,
            "pix": pix,
            "can_operate": can_operate_payment,
        }

    if payment.status != PaymentIntent.Status.PAID:
        return {
            "kind": "payment_closed",
            "title": "Pagamento sem cobrança ativa",
            "description": "Revise o pagamento antes de continuar a operação.",
            "payment": payment,
        }

    fulfillment = _active_fulfillment(organization=organization, order=order)
    can_operate_fulfillment = fulfillment_policies.can_operate_fulfillments(
        user=user,
        organization=organization,
    )
    if fulfillment is None:
        return {
            "kind": "create_fulfillment",
            "title": "Pedido pago",
            "description": "Crie o atendimento de entrega ou retirada.",
            "can_operate": can_operate_fulfillment,
        }

    target = None
    label = None
    description = None
    if fulfillment.status == Fulfillment.Status.DRAFT:
        target = Fulfillment.Status.PREPARING
        label = "Iniciar preparação"
        description = "O atendimento está pronto para entrar em preparação."
    elif fulfillment.status == Fulfillment.Status.PREPARING:
        target = Fulfillment.Status.READY
        label = "Liberar para retirada" if fulfillment.method == Fulfillment.Method.PICKUP else "Marcar como pronto"
        description = "Finalize a preparação para liberar a próxima etapa."
    elif fulfillment.status == Fulfillment.Status.READY:
        if fulfillment.method == Fulfillment.Method.PICKUP:
            target = Fulfillment.Status.COMPLETED
            label = "Confirmar retirada"
            description = "O pedido está pronto e aguarda a retirada do cliente."
        else:
            target = Fulfillment.Status.IN_TRANSIT
            label = "Marcar como enviado"
            description = "O pedido está pronto para despacho."
    elif fulfillment.status == Fulfillment.Status.IN_TRANSIT:
        target = Fulfillment.Status.COMPLETED
        label = "Confirmar entrega"
        description = "O pedido está em trânsito e pode ser concluído após entrega confirmada."

    return {
        "kind": "fulfillment_transition" if target else "closed",
        "title": label or "Atendimento concluído",
        "description": description or "Nenhuma próxima ação disponível.",
        "fulfillment": fulfillment,
        "target_status": target,
        "label": label,
        "can_operate": can_operate_fulfillment,
    }
