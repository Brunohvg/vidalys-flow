from django.db.models import Q

from apps.payments.models import PaymentIntent
from apps.payments.policies import MANAGER_ROLES


def payments_for_organization(*, organization):
    return PaymentIntent.objects.filter(organization=organization).select_related("order", "created_by")


def search_payments(*, organization, query="", status=""):
    queryset = payments_for_organization(organization=organization)
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(
            Q(order_number_snapshot__icontains=query)
            | Q(customer_name_snapshot__icontains=query)
        )
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def payment_for_organization(*, organization, payment_id):
    return payments_for_organization(organization=organization).filter(id=payment_id).first()


def payment_detail(*, organization, payment, user, membership):
    if payment.organization_id != organization.id:
        return None
    if (
        membership.organization_id != organization.id
        or membership.user_id != user.id
        or not membership.is_active
    ):
        return None
    manager = membership.role in MANAGER_ROLES
    attempts = list(payment.attempts.select_related("provider_account").order_by("created_at"))
    attempt_rows = []
    for attempt in attempts:
        attempt_rows.append(
            {
                "id": attempt.id,
                "provider": attempt.get_provider_display(),
                "status": attempt.get_status_display(),
                "hosted_url": attempt.hosted_url if attempt.status == attempt.Status.ACTIVE else "",
                "expires_at": attempt.expires_at,
                "external_resource_id": attempt.external_resource_id if manager else "",
                "provider_account": attempt.provider_account.display_name if manager else "",
            }
        )
    return {
        "customer_name": payment.customer_name_snapshot if manager else "••••",
        "attention_code": payment.attention_code if manager else "",
        "attempts": attempt_rows,
        "history": payment.status_history.select_related("actor").all(),
    }

