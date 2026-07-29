from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.organizations.selectors import memberships_for_user


@login_required
def organization_list(request):
    memberships = memberships_for_user(user=request.user)
    return render(
        request,
        "organizations/list.html",
        {"memberships": memberships},
    )
