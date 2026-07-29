from apps.organizations.models import Membership, Organization

ACTIVE_ORGANIZATION_SESSION_KEY = "active_organization_id"


def organizations_for_user(*, user):
    if not user.is_authenticated or not user.is_active:
        return Organization.objects.none()
    return Organization.objects.filter(
        is_active=True,
        memberships__user=user,
        memberships__is_active=True,
    ).distinct()


def memberships_for_user(*, user):
    return Membership.objects.filter(
        user=user,
        is_active=True,
        organization__is_active=True,
    ).select_related("organization")


def active_organization_for_user(*, user, session):
    memberships = memberships_for_user(user=user)
    selected_id = session.get(ACTIVE_ORGANIZATION_SESSION_KEY)
    if selected_id:
        selected = memberships.filter(organization_id=selected_id).first()
        if selected:
            return selected.organization, selected
        session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
    if memberships.count() == 1:
        membership = memberships.first()
        session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(membership.organization_id)
        return membership.organization, membership
    return None, None
