from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.organizations.selectors import ACTIVE_ORGANIZATION_SESSION_KEY, memberships_for_user


@login_required
def organization_list(request):
    memberships = memberships_for_user(user=request.user)
    return render(
        request,
        "organizations/list.html",
        {"memberships": memberships},
    )


@login_required
@require_POST
def select_organization(request, organization_id):
    membership = memberships_for_user(user=request.user).filter(organization_id=organization_id).first()
    if not membership:
        raise Http404
    request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(membership.organization_id)
    return redirect("customers:list")
