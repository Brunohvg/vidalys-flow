import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent
from apps.audit.services import REDACTED, record_event
from apps.organizations.models import Organization

User = get_user_model()


@pytest.mark.django_db
def test_records_sanitized_audit_event():
    organization = Organization.objects.create(name="Org", slug="org")
    user = User.objects.create_user("owner@example.com")
    event = record_event(
        organization=organization,
        actor=user,
        action="organization.created",
        entity_type="organization",
        entity_id=organization.id,
        payload={"name": "Org", "api_token": "must-not-persist", "nested": {"password": "hidden"}},
    )
    assert event.payload == {
        "name": "Org",
        "api_token": REDACTED,
        "nested": {"password": REDACTED},
    }
    assert event.actor == user


@pytest.mark.django_db
def test_actor_is_optional():
    organization = Organization.objects.create(name="Org", slug="org")
    event = record_event(
        organization=organization,
        action="system.ready",
        entity_type="system",
        entity_id="ready",
    )
    assert event.actor is None


@pytest.mark.django_db
def test_audit_events_are_isolated_by_organization():
    first = Organization.objects.create(name="First", slug="first")
    second = Organization.objects.create(name="Second", slug="second")
    record_event(organization=first, action="test", entity_type="test", entity_id="1")
    record_event(organization=second, action="test", entity_type="test", entity_id="2")
    assert AuditEvent.objects.filter(organization=first).count() == 1
    assert AuditEvent.objects.filter(organization=second).count() == 1
