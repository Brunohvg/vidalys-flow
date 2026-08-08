from apps.organizations.models import Membership
from apps.organizations.policies import active_membership_for

MANAGER_ROLES = {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MANAGER}


def membership_for(*, user, organization):
    return active_membership_for(user=user, organization=organization)


def can_view_orders(*, user, organization):
    return membership_for(user=user, organization=organization) is not None


def can_manage_drafts(*, user, organization):
    return membership_for(user=user, organization=organization) is not None


def can_confirm_orders(*, user, organization):
    return membership_for(user=user, organization=organization) is not None


def can_apply_adjustments(*, user, organization):
    membership = membership_for(user=user, organization=organization)
    return bool(membership and membership.role in MANAGER_ROLES)


def can_cancel_orders(*, user, organization):
    return can_apply_adjustments(user=user, organization=organization)


def can_view_unmasked_personal_data(*, user, organization):
    return can_apply_adjustments(user=user, organization=organization)
