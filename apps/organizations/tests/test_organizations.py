import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.organizations.exceptions import LastActiveOwnerError
from apps.organizations.models import Membership, Organization, OrganizationUnit
from apps.organizations.policies import active_membership_for, can_access_organization, can_manage_memberships
from apps.organizations.services import bootstrap_organization, deactivate_membership

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user("owner@example.com", "safe-test-password")


@pytest.fixture
def organization():
    return Organization.objects.create(name="Loja A", slug="loja-a")


@pytest.mark.django_db
def test_create_organization_and_unit(organization):
    unit = OrganizationUnit.objects.create(organization=organization, name="Matriz")
    assert unit.organization == organization
    assert unit.is_active


@pytest.mark.django_db
def test_slug_is_case_insensitively_unique(organization):
    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(name="Outra", slug="LOJA-A")


@pytest.mark.django_db
def test_unit_name_is_unique_per_organization(organization):
    OrganizationUnit.objects.create(organization=organization, name="Matriz")
    with pytest.raises(IntegrityError), transaction.atomic():
        OrganizationUnit.objects.create(organization=organization, name="Matriz")


@pytest.mark.django_db
@pytest.mark.parametrize("role", Membership.Role.values)
def test_membership_roles_are_valid(user, organization, role):
    membership = Membership.objects.create(organization=organization, user=user, role=role)
    assert membership.role == role


@pytest.mark.django_db
def test_invalid_membership_role_is_rejected(user, organization):
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(organization=organization, user=user, role="invalid")


@pytest.mark.django_db
def test_user_can_belong_to_multiple_organizations(user):
    first = Organization.objects.create(name="Primeira", slug="primeira")
    second = Organization.objects.create(name="Segunda", slug="segunda")
    Membership.objects.create(organization=first, user=user, role=Membership.Role.OWNER)
    Membership.objects.create(organization=second, user=user, role=Membership.Role.OPERATOR)
    assert user.memberships.count() == 2


@pytest.mark.django_db
def test_organization_list_is_isolated(client, user):
    visible = Organization.objects.create(name="Visível", slug="visivel")
    hidden = Organization.objects.create(name="Oculta", slug="oculta")
    Membership.objects.create(organization=visible, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    response = client.get(reverse("organizations:list"))
    content = response.content.decode()
    assert "Visível" in content
    assert hidden.name not in content


@pytest.mark.django_db
def test_inactive_membership_is_not_listed(client, user, organization):
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Membership.Role.OWNER,
        is_active=False,
    )
    client.force_login(user)
    response = client.get(reverse("organizations:list"))
    assert organization.name not in response.content.decode()


@pytest.mark.django_db
def test_membership_policies_require_active_user_and_membership(user, organization):
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=Membership.Role.OPERATOR,
    )
    assert active_membership_for(user=user, organization=organization) == membership
    assert can_access_organization(user=user, organization=organization)
    assert not can_manage_memberships(user=user, organization=organization)
    membership.is_active = False
    membership.save(update_fields=("is_active",))
    assert active_membership_for(user=user, organization=organization) is None
    assert not can_access_organization(user=user, organization=organization)


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Membership.Role.OWNER, Membership.Role.ADMIN])
def test_owner_and_admin_can_manage_memberships(user, organization, role):
    Membership.objects.create(organization=organization, user=user, role=role)
    assert can_manage_memberships(user=user, organization=organization)


@pytest.mark.django_db
def test_last_active_owner_cannot_be_deactivated(user, organization):
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=Membership.Role.OWNER,
    )
    with pytest.raises(LastActiveOwnerError):
        deactivate_membership(membership=membership)
    membership.refresh_from_db()
    assert membership.is_active


@pytest.mark.django_db
def test_owner_can_be_deactivated_when_another_owner_remains(user, organization):
    second_user = User.objects.create_user("second@example.com", "safe-test-password")
    first = Membership.objects.create(organization=organization, user=user, role=Membership.Role.OWNER)
    Membership.objects.create(organization=organization, user=second_user, role=Membership.Role.OWNER)
    deactivate_membership(membership=first)
    first.refresh_from_db()
    assert not first.is_active


@pytest.mark.django_db
def test_bootstrap_is_idempotent():
    kwargs = {
        "organization_name": "Vidalys Test",
        "slug": "vidalys-test",
        "owner_email": "owner@example.com",
        "owner_name": "Owner Test",
        "unit_name": "Matriz",
    }
    first = bootstrap_organization(**kwargs)
    second = bootstrap_organization(**kwargs)
    assert first.organization == second.organization
    assert first.user == second.user
    assert Organization.objects.count() == 1
    assert Membership.objects.count() == 1
    assert OrganizationUnit.objects.count() == 1


@pytest.mark.django_db
def test_bootstrap_command_never_sets_a_password(capsys):
    call_command(
        "bootstrap_organization",
        organization_name="Vidalys Test",
        slug="vidalys-test",
        owner_email="owner@example.com",
        owner_name="Owner Test",
        unit_name="Matriz",
    )
    user = User.objects.get()
    output = capsys.readouterr().out
    assert not user.has_usable_password()
    assert user.email not in output
