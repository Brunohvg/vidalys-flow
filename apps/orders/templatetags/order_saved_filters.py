from django import template

from apps.orders.saved_filter_views import SESSION_KEY

register = template.Library()


@register.simple_tag(takes_context=True)
def order_saved_filters(context):
    request = context["request"]
    organization = context["organization"]
    organization_id = str(organization.id)
    return [
        entry
        for entry in request.session.get(SESSION_KEY, [])
        if entry.get("organization_id") == organization_id
    ]
