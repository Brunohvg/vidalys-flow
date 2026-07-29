from apps.organizations.models import Membership


def active_membership_for(*, user, organization):
    if not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.filter(
        user=user,
        organization=organization,
        organization__is_active=True,
        is_active=True,
    ).first()


def can_access_organization(*, user, organization):
    return active_membership_for(user=user, organization=organization) is not None


def can_manage_memberships(*, user, organization):
    membership = active_membership_for(user=user, organization=organization)
    return bool(membership and membership.role in {Membership.Role.OWNER, Membership.Role.ADMIN})
