import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import QueryDict
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.orders import policies
from apps.orders.forms import OrderFilterForm
from apps.organizations.selectors import active_organization_for_user

SESSION_KEY = "order_saved_filters_v1"
MAX_SAVED_FILTERS_PER_ORGANIZATION = 10
ALLOWED_QUERY_KEYS = frozenset({"q", "status", "channel", "created_from", "created_to"})


def _organization(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if (
        not organization
        or not membership
        or not policies.can_view_orders(user=request.user, organization=organization)
    ):
        return None
    return organization


def _normalized_querystring(raw):
    params = QueryDict(raw or "", mutable=True)
    for key in list(params.keys()):
        if key not in ALLOWED_QUERY_KEYS:
            params.pop(key, None)
    form = OrderFilterForm(params)
    if not form.is_valid():
        return ""
    normalized = QueryDict("", mutable=True)
    for key in ALLOWED_QUERY_KEYS:
        value = form.cleaned_data.get(key)
        if value in (None, ""):
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        normalized[key] = str(value)
    return normalized.urlencode()


@login_required
@require_POST
def save_order_filter(request):
    organization = _organization(request)
    if organization is None:
        return redirect("organizations:list")
    name = " ".join((request.POST.get("name") or "").split())[:50]
    querystring = _normalized_querystring(request.POST.get("querystring", ""))
    if not name:
        messages.error(request, "Informe um nome para o filtro salvo.")
        return redirect("orders:list")
    if not querystring:
        messages.error(request, "Aplique ao menos um filtro antes de salvar.")
        return redirect("orders:list")

    organization_id = str(organization.id)
    entries = list(request.session.get(SESSION_KEY, []))
    scoped = [entry for entry in entries if entry.get("organization_id") == organization_id]
    other = [entry for entry in entries if entry.get("organization_id") != organization_id]
    scoped = [entry for entry in scoped if entry.get("name", "").casefold() != name.casefold()]
    scoped.insert(
        0,
        {
            "id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "name": name,
            "querystring": querystring,
        },
    )
    request.session[SESSION_KEY] = other + scoped[:MAX_SAVED_FILTERS_PER_ORGANIZATION]
    request.session.modified = True
    messages.success(request, f'Filtro "{name}" salvo para esta Organization.')
    return redirect(f"{request.path.rsplit('/filters/', 1)[0]}/?{querystring}")


@login_required
@require_POST
def delete_order_filter(request, filter_id):
    organization = _organization(request)
    if organization is None:
        return redirect("organizations:list")
    organization_id = str(organization.id)
    entries = list(request.session.get(SESSION_KEY, []))
    request.session[SESSION_KEY] = [
        entry
        for entry in entries
        if not (
            entry.get("organization_id") == organization_id
            and entry.get("id") == str(filter_id)
        )
    ]
    request.session.modified = True
    messages.success(request, "Filtro salvo removido.")
    return redirect("orders:list")
