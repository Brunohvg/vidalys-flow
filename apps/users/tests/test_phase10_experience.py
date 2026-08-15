import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.organizations.models import Membership
from apps.users.team_services import (
    TeamInvariantError,
    TeamPermissionDenied,
    can_manage_team,
    can_view_team,
    team_memberships,
    update_membership,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


def _member(*, organization, email, role, active=True):
    user = User.objects.create_user(email, "safe-test-password")
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=role,
        is_active=active,
    )
    return user, membership


def test_team_permissions_and_listing(organization):
    owner, owner_membership = _member(
        organization=organization,
        email="owner-team@example.com",
        role=Membership.Role.OWNER,
    )
    manager, manager_membership = _member(
        organization=organization,
        email="manager-team@example.com",
        role=Membership.Role.MANAGER,
    )
    operator, _ = _member(
        organization=organization,
        email="operator-team@example.com",
        role=Membership.Role.OPERATOR,
    )

    assert can_view_team(organization=organization, actor=owner)
    assert can_manage_team(organization=organization, actor=owner)
    assert can_view_team(organization=organization, actor=manager)
    assert not can_manage_team(organization=organization, actor=manager)
    assert not can_view_team(organization=organization, actor=operator)
    assert list(team_memberships(organization=organization, actor=manager)) == [
        manager_membership,
        operator.memberships.get(organization=organization),
        owner_membership,
    ]
    with pytest.raises(TeamPermissionDenied):
        team_memberships(organization=organization, actor=operator)


def test_update_membership_requires_admin_and_preserves_last_owner(organization):
    owner, owner_membership = _member(
        organization=organization,
        email="owner-update@example.com",
        role=Membership.Role.OWNER,
    )
    manager, manager_membership = _member(
        organization=organization,
        email="manager-update@example.com",
        role=Membership.Role.MANAGER,
    )
    target, target_membership = _member(
        organization=organization,
        email="target-update@example.com",
        role=Membership.Role.OPERATOR,
    )

    with pytest.raises(TeamPermissionDenied):
        update_membership(
            organization=organization,
            actor=manager,
            membership_id=target_membership.id,
            role=Membership.Role.MANAGER,
            is_active=True,
        )
    with pytest.raises(TeamInvariantError, match="Papel inválido"):
        update_membership(
            organization=organization,
            actor=owner,
            membership_id=target_membership.id,
            role="invalid",
            is_active=True,
        )
    with pytest.raises(TeamInvariantError, match="não pertence"):
        update_membership(
            organization=organization,
            actor=owner,
            membership_id=owner.id,
            role=Membership.Role.OPERATOR,
            is_active=True,
        )
    with pytest.raises(TeamInvariantError, match="pelo menos um proprietário"):
        update_membership(
            organization=organization,
            actor=owner,
            membership_id=owner_membership.id,
            role=Membership.Role.ADMIN,
            is_active=True,
        )

    updated = update_membership(
        organization=organization,
        actor=owner,
        membership_id=target_membership.id,
        role=Membership.Role.MANAGER,
        is_active=False,
    )
    assert updated.user == target
    assert updated.role == Membership.Role.MANAGER
    assert updated.is_active is False
    assert AuditEvent.objects.filter(
        organization=organization,
        action="organization.membership_updated",
        entity_id=str(target_membership.id),
    ).exists()


def test_owner_can_demote_an_owner_when_another_active_owner_exists(organization):
    owner, owner_membership = _member(
        organization=organization,
        email="owner-one@example.com",
        role=Membership.Role.OWNER,
    )
    _member(
        organization=organization,
        email="owner-two@example.com",
        role=Membership.Role.OWNER,
    )

    updated = update_membership(
        organization=organization,
        actor=owner,
        membership_id=owner_membership.id,
        role=Membership.Role.ADMIN,
        is_active=True,
    )
    assert updated.role == Membership.Role.ADMIN


def test_profile_settings_and_team_views(
    client,
    organization,
    manager,
    manager_membership,
):
    client.force_login(manager)

    profile = client.get(reverse("users:profile"))
    settings = client.get(reverse("users:settings"))
    team = client.get(reverse("users:team"))
    update = client.post(
        reverse("users:profile"),
        {"first_name": "  Maria ", "last_name": " Silva "},
    )

    manager.refresh_from_db()
    assert profile.status_code == 200
    assert settings.status_code == 200
    assert "Configurações" in settings.content.decode()
    assert team.status_code == 200
    assert update.status_code == 302
    assert manager.first_name == "Maria"
    assert manager.last_name == "Silva"


def test_operator_cannot_open_team_but_can_open_settings(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    assert client.get(reverse("users:team")).status_code == 404
    settings = client.get(reverse("users:settings"))
    content = settings.content.decode()
    assert settings.status_code == 200
    assert "Equipe e acessos" not in content
    assert "Auditoria" not in content


def test_team_update_view_rejects_invalid_form_and_last_owner_change(client, organization):
    owner, owner_membership = _member(
        organization=organization,
        email="owner-view@example.com",
        role=Membership.Role.OWNER,
    )
    client.force_login(owner)

    invalid = client.post(reverse("users:team-update", args=(owner_membership.id,)), {"role": "invalid"})
    protected = client.post(
        reverse("users:team-update", args=(owner_membership.id,)),
        {"role": Membership.Role.ADMIN, "is_active": "on"},
    )

    assert invalid.status_code == 302
    assert protected.status_code == 302
    owner_membership.refresh_from_db()
    assert owner_membership.role == Membership.Role.OWNER
