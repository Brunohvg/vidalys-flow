import pytest
from django.contrib.auth import get_user_model

from apps.organizations.models import Membership, Organization

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user("operator@example.com", "safe-test-password")


@pytest.fixture
def manager():
    return User.objects.create_user("manager@example.com", "safe-test-password")


@pytest.fixture
def outsider():
    return User.objects.create_user("outsider@example.com", "safe-test-password")


@pytest.fixture
def organization():
    return Organization.objects.create(name="Organização A", slug="organizacao-a")


@pytest.fixture
def other_organization():
    return Organization.objects.create(name="Organização B", slug="organizacao-b")


@pytest.fixture
def operator_membership(user, organization):
    return Membership.objects.create(
        organization=organization,
        user=user,
        role=Membership.Role.OPERATOR,
    )


@pytest.fixture
def manager_membership(manager, organization):
    return Membership.objects.create(
        organization=organization,
        user=manager,
        role=Membership.Role.MANAGER,
    )
