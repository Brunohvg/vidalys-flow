import pytest
from django.urls import reverse

from apps.audit.services import record_event
from apps.organizations.models import Membership

pytestmark = pytest.mark.django_db


def test_audit_requires_manager_tier(client, organization, user, operator_membership):
    client.force_login(user)
    assert client.get(reverse("audit:list")).status_code == 404


def test_audit_is_tenant_scoped(
    client,
    organization,
    other_organization,
    manager,
    manager_membership,
):
    record_event(
        organization=organization,
        actor=manager,
        action="test.visible",
        entity_type="order",
        entity_id="visible",
        payload={},
    )
    other_manager = type(manager).objects.create_user("audit-other@example.com", "safe-test-password")
    Membership.objects.create(
        organization=other_organization,
        user=other_manager,
        role=Membership.Role.MANAGER,
    )
    record_event(
        organization=other_organization,
        actor=other_manager,
        action="test.hidden",
        entity_type="order",
        entity_id="hidden",
        payload={},
    )

    client.force_login(manager)
    response = client.get(reverse("audit:list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "test.visible" in content
    assert "test.hidden" not in content
