from django.db.models import Q

from apps.messaging.models import Message, MessageTemplate, MessagingChannel, MessagingProviderConnection
from apps.messaging.policies import MANAGER_ROLES

MASKED_DESTINATION = "••••"


def _mask_destination(destination, *, channel_kind):
    if not destination:
        return MASKED_DESTINATION
    if channel_kind == MessagingChannel.Kind.EMAIL:
        local, _, domain = destination.partition("@")
        if not domain:
            return MASKED_DESTINATION
        visible = local[:2] if len(local) >= 2 else local[:1]
        return f"{visible}{'•' * max(2, len(local) - len(visible))}@{domain}"
    digits = "".join(ch for ch in destination if ch.isdigit())
    if len(digits) <= 4:
        return MASKED_DESTINATION
    return f"••••{digits[-4:]}"


def messages_for_organization(*, organization):
    return Message.objects.filter(organization=organization).select_related("template", "channel", "customer")


def search_messages(*, organization, query="", status=""):
    queryset = messages_for_organization(organization=organization)
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(
            Q(customer_display_name__icontains=query)
            | Q(template_semantic_key__icontains=query)
            | Q(purpose__icontains=query)
        )
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def message_for_organization(*, organization, message_id):
    return messages_for_organization(organization=organization).filter(id=message_id).first()


def message_detail(*, organization, message, user, membership):
    if message.organization_id != organization.id:
        return None
    if membership.organization_id != organization.id or membership.user_id != user.id or not membership.is_active:
        return None
    manager = membership.role in MANAGER_ROLES
    attempts = list(message.attempts.select_related("channel").order_by("created_at"))
    attempt_rows = [
        {
            "id": attempt.id,
            "status": attempt.get_status_display(),
            "external_message_id": attempt.external_message_id if manager else "",
            "dispatch_attempts": attempt.dispatch_attempts,
            "dispatch_error_code": attempt.dispatch_error_code if manager else "",
        }
        for attempt in attempts
    ]
    return {
        "destination": message.destination_snapshot
        if manager
        else _mask_destination(
            message.destination_snapshot,
            channel_kind=message.channel_kind,
        ),
        "customer_name": message.customer_display_name,
        "template": message.template_semantic_key,
        "attempts": attempt_rows,
        "history": message.status_history.select_related("actor").all(),
    }


def channels_for_organization(*, organization):
    return MessagingChannel.objects.filter(organization=organization).select_related("connection")


def connections_for_organization(*, organization):
    return MessagingProviderConnection.objects.filter(organization=organization)


def templates_for_organization(*, organization):
    return MessageTemplate.objects.filter(organization=organization)
