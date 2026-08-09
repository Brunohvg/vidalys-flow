from apps.organizations.models import Membership
from apps.organizations.policies import active_membership_for

MANAGER_ROLES = {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MANAGER}


def membership_for(*, user, organization):
    return active_membership_for(user=user, organization=organization)


def can_view_payments(*, user, organization):
    return membership_for(user=user, organization=organization) is not None


def can_operate_payments(*, user, organization):
    membership = membership_for(user=user, organization=organization)
    return bool(membership and membership.role in MANAGER_ROLES)


def can_view_provider_evidence(*, user, organization):
    return can_operate_payments(user=user, organization=organization)

