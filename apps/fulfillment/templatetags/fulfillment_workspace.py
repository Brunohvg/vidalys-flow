import uuid

from django import template

from apps.fulfillment import policies
from apps.fulfillment.forms import TrackingForm
from apps.fulfillment.models import Fulfillment

register = template.Library()


TRANSITIONS = {
    Fulfillment.Status.DRAFT: (Fulfillment.Status.PREPARING, "Iniciar preparação"),
    Fulfillment.Status.PREPARING: (Fulfillment.Status.READY, "Marcar como pronto"),
    Fulfillment.Status.READY: (Fulfillment.Status.IN_TRANSIT, "Marcar como enviado"),
    Fulfillment.Status.IN_TRANSIT: (Fulfillment.Status.COMPLETED, "Confirmar entrega"),
}


@register.inclusion_tag("fulfillment/_order_workspace.html", takes_context=True)
def fulfillment_order_workspace(context, organization, order):
    request = context["request"]
    membership = policies.membership_for(user=request.user, organization=organization)
    if membership is None or order.organization_id != organization.id:
        return {"visible": False}

    can_operate = policies.can_operate_fulfillments(user=request.user, organization=organization)
    rows = []
    fulfillments = order.fulfillments.filter(organization=organization).order_by("sequence")
    for fulfillment in fulfillments:
        target_status = ""
        transition_label = ""
        transition = TRANSITIONS.get(fulfillment.status)
        if transition:
            target_status, transition_label = transition
        if fulfillment.method == Fulfillment.Method.PICKUP and fulfillment.status == Fulfillment.Status.READY:
            target_status = ""
            transition_label = ""

        tracking_form = None
        if (
            can_operate
            and fulfillment.method == Fulfillment.Method.DELIVERY
            and fulfillment.status in {Fulfillment.Status.READY, Fulfillment.Status.IN_TRANSIT}
        ):
            tracking_form = TrackingForm(
                initial={
                    "expected_version": fulfillment.version,
                    "idempotency_key": str(uuid.uuid4()),
                    "tracking_code": fulfillment.tracking_code,
                    "tracking_url": fulfillment.tracking_url,
                }
            )

        rows.append(
            {
                "fulfillment": fulfillment,
                "target_status": target_status,
                "transition_label": transition_label,
                "transition_key": str(uuid.uuid4()),
                "tracking_form": tracking_form,
            }
        )

    return {
        "visible": True,
        "organization": organization,
        "order": order,
        "rows": rows,
        "can_operate": can_operate,
    }
