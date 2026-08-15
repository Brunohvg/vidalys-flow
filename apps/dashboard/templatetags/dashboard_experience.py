import uuid

from django import template

from apps.dashboard.order_actions import order_next_action

register = template.Library()


@register.inclusion_tag("dashboard/_order_next_action.html", takes_context=True)
def order_next_action_card(context, organization, order):
    request = context["request"]
    action = order_next_action(
        organization=organization,
        order=order,
        user=request.user,
    )
    return {
        "request": request,
        "organization": organization,
        "order": order,
        "action": action,
        "idempotency_key": str(uuid.uuid4()),
    }
