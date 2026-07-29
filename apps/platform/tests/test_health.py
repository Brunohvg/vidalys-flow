import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_liveness_does_not_require_dependencies(client):
    response = client.get(reverse("platform:live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_is_healthy_with_dependencies(client):
    response = client.get(reverse("platform:ready"))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.django_db
def test_readiness_is_unhealthy_when_database_fails(client, monkeypatch):
    def fail():
        raise RuntimeError

    monkeypatch.setattr("apps.platform.health.database_status", fail)
    response = client.get(reverse("platform:ready"))
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


@pytest.mark.django_db
def test_readiness_is_unhealthy_when_redis_fails(client, monkeypatch):
    def fail():
        raise RuntimeError

    monkeypatch.setattr("apps.platform.health.cache_status", fail)
    response = client.get(reverse("platform:ready"))
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "unavailable"
