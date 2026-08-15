from django.db import transaction

from apps.audit.services import record_event
from apps.organizations.models import Membership

TEAM_MANAGER_ROLES = {Membership.Role.OWNER, Membership.Role.ADMIN}
TEAM_VIEW_ROLES = TEAM_MANAGER_ROLES | {Membership.Role.MANAGER}


class TeamPermissionDenied(PermissionError):
    pass


class TeamInvariantError(ValueError):
    pass


def _actor_membership(*, organization, actor):
    return Membership.objects.filter(
        organization=organization,
        user=actor,
        is_active=True,
    ).first()


def can_view_team(*, organization, actor):
    membership = _actor_membership(organization=organization, actor=actor)
    return bool(membership and membership.role in TEAM_VIEW_ROLES)


def can_manage_team(*, organization, actor):
    membership = _actor_membership(organization=organization, actor=actor)
    return bool(membership and membership.role in TEAM_MANAGER_ROLES)


def team_memberships(*, organization, actor):
    if not can_view_team(organization=organization, actor=actor):
        raise TeamPermissionDenied("Acesso à equipe exige papel de gerência.")
    return Membership.objects.filter(organization=organization).select_related("user").order_by("user__email")


@transaction.atomic
def update_membership(*, organization, actor, membership_id, role, is_active):
    if not can_manage_team(organization=organization, actor=actor):
        raise TeamPermissionDenied("Somente proprietário ou administrador pode alterar a equipe.")
    if role not in Membership.Role.values:
        raise TeamInvariantError("Papel inválido.")

    membership = (
        Membership.objects.select_for_update()
        .select_related("user")
        .filter(organization=organization, id=membership_id)
        .first()
    )
    if membership is None:
        raise TeamInvariantError("Membership não pertence à organização.")

    if membership.role == Membership.Role.OWNER and (
        role != Membership.Role.OWNER or not is_active
    ):
        active_owners = Membership.objects.select_for_update().filter(
            organization=organization,
            role=Membership.Role.OWNER,
            is_active=True,
        )
        if active_owners.count() <= 1:
            raise TeamInvariantError("A organização precisa manter pelo menos um proprietário ativo.")

    before = {"role": membership.role, "is_active": membership.is_active}
    membership.role = role
    membership.is_active = bool(is_active)
    membership.save(update_fields=("role", "is_active", "updated_at"))
    record_event(
        organization=organization,
        actor=actor,
        action="organization.membership_updated",
        entity_type="membership",
        entity_id=membership.id,
        payload={
            "before_role": before["role"],
            "after_role": membership.role,
            "before_active": before["is_active"],
            "after_active": membership.is_active,
        },
    )
    return membership
