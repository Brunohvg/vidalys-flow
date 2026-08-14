from apps.organizations.models import Membership


def can_configure_integrations(user, organization):
    return Membership.objects.filter(user=user, organization=organization, is_active=True, role__in=(Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MANAGER)).exists()


def can_view_integrations(user, organization):
    return Membership.objects.filter(user=user, organization=organization, is_active=True).exists()
