from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.organizations.selectors import active_organization_for_user

from . import policies
from .selectors import connections_for_organization, deliveries_for_organization


@login_required
def integration_list(request):
    organization, _ = active_organization_for_user(user=request.user, session=request.session)
    if not organization or not policies.can_view_integrations(request.user, organization):
        messages.info(request, "Selecione uma organização ativa para continuar.")
        return redirect("organizations:list")
    connections = connections_for_organization(organization)
    deliveries = Paginator(deliveries_for_organization(organization), 25).get_page(request.GET.get("page"))
    return render(
        request,
        "integrations/list.html",
        {"organization": organization, "connections": connections, "deliveries": deliveries},
    )
