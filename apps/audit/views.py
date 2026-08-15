from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render

from apps.audit.models import AuditEvent
from apps.organizations.models import Membership
from apps.organizations.selectors import active_organization_for_user

MANAGER_ROLES = {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MANAGER}


def _manager_context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or membership is None:
        messages.info(request, "Selecione uma organização ativa para continuar.")
        return None, None, redirect("organizations:list")
    if not membership.is_active or membership.role not in MANAGER_ROLES:
        raise Http404
    return organization, membership, None


@login_required
def audit_list(request):
    organization, _, response = _manager_context_or_redirect(request)
    if response:
        return response

    query = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()
    entity_type = (request.GET.get("entity_type") or "").strip()
    events = AuditEvent.objects.filter(organization=organization).select_related("actor")
    if query:
        events = events.filter(entity_id__icontains=query)
    if action:
        events = events.filter(action__icontains=action)
    if entity_type:
        events = events.filter(entity_type__icontains=entity_type)

    page = Paginator(events, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "audit/list.html",
        {
            "organization": organization,
            "events": page,
            "query": query,
            "action_filter": action,
            "entity_type_filter": entity_type,
        },
    )
