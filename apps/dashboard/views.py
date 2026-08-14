from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from apps.organizations.selectors import active_organization_for_user

from .selectors import (
    dashboard_search_for_organization,
    dashboard_summary,
    fulfillment_attention_for_organization,
    integration_attention_for_organization,
    message_attention_for_organization,
    order_workspace_for_organization,
    payment_attention_for_organization,
    recent_orders_for_organization,
)


def _active_organization_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or membership is None:
        messages.info(request, "Selecione uma organização ativa para continuar.")
        return None, redirect("organizations:list")
    return organization, None


@login_required
def dashboard_home(request):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    search_query = request.GET.get("q", "").strip()
    integrations = integration_attention_for_organization(organization=organization)
    return render(
        request,
        "dashboard/home.html",
        {
            "organization": organization,
            "summary": dashboard_summary(organization=organization),
            "recent_orders": recent_orders_for_organization(organization=organization),
            "payment_attention": payment_attention_for_organization(organization=organization),
            "fulfillment_attention": fulfillment_attention_for_organization(organization=organization),
            "message_attention": message_attention_for_organization(organization=organization),
            "integration_connections": integrations["connections"],
            "integration_deliveries": integrations["deliveries"],
            "search_query": search_query,
            "search_results": dashboard_search_for_organization(organization=organization, query=search_query),
        },
    )


@login_required
def order_workspace(request, order_id):
    organization, response = _active_organization_or_redirect(request)
    if response:
        return response
    workspace = order_workspace_for_organization(organization=organization, order_id=order_id)
    if workspace is None:
        raise Http404("Pedido não encontrado.")
    return render(request, "dashboard/order_workspace.html", {"organization": organization, **workspace})
