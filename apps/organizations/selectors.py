from apps.organizations.models import Membership, Organization


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
