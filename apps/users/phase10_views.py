from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.organizations.selectors import active_organization_for_user
from apps.users.phase10_forms import MembershipUpdateForm, ProfileForm
from apps.users.team_services import (
    TeamInvariantError,
    TeamPermissionDenied,
    can_manage_team,
    team_memberships,
    update_membership,
)


@login_required
def profile(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    form = ProfileForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        request.user.first_name = form.cleaned_data["first_name"].strip()
        request.user.last_name = form.cleaned_data["last_name"].strip()
        request.user.save(update_fields=("first_name", "last_name", "updated_at"))
        messages.success(request, "Perfil atualizado.")
        return redirect("users:profile")
    return render(
        request,
        "users/profile.html",
        {
            "organization": organization,
            "membership": membership,
            "form": form,
        },
    )


@login_required
def team(request):
    organization, _membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None:
        raise Http404
    try:
        memberships = team_memberships(organization=organization, actor=request.user)
    except TeamPermissionDenied as exc:
        raise Http404 from exc
    return render(
        request,
        "users/team.html",
        {
            "organization": organization,
            "memberships": memberships,
            "can_manage": can_manage_team(organization=organization, actor=request.user),
        },
    )


@login_required
@require_POST
def team_update(request, membership_id):
    organization, _membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None:
        raise Http404
    form = MembershipUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Alteração de usuário inválida.")
        return redirect("users:team")
    try:
        update_membership(
            organization=organization,
            actor=request.user,
            membership_id=membership_id,
            **form.cleaned_data,
        )
    except (TeamPermissionDenied, TeamInvariantError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Acesso do usuário atualizado.")
    return redirect("users:team")
