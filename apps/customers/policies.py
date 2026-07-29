from apps.organizations.models import Membership
from apps.organizations.policies import active_membership_for

MANAGER_ROLES = {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MANAGER}


def membership_for(*, user, organization):
    return active_membership_for(user=user, organization=organization)


def can_view_customers(*, user, organization):
    return membership_for(user=user, organization=organization) is not None


def can_manage_customers(*, user, organization):
    return membership_for(user=user, organization=organization) is not None


def can_merge_customers(*, user, organization):
    membership = membership_for(user=user, organization=organization)
    return bool(membership and membership.role in MANAGER_ROLES)


def can_block_customers(*, user, organization):
    return can_merge_customers(user=user, organization=organization)
