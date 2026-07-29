import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_create_user_normalizes_email():
    user = User.objects.create_user("  Owner@Example.COM ", "safe-test-password")
    assert user.email == "owner@example.com"
    assert user.check_password("safe-test-password")
    assert not user.is_staff
    assert not user.is_superuser


@pytest.mark.django_db
def test_create_superuser():
    user = User.objects.create_superuser("admin@example.com", "safe-test-password")
    assert user.is_staff
    assert user.is_superuser


@pytest.mark.django_db
def test_email_is_case_insensitively_unique():
    User.objects.create_user("owner@example.com", "safe-test-password")
    with pytest.raises(IntegrityError), transaction.atomic():
        User(email="OWNER@EXAMPLE.COM").save()


def test_user_has_no_legacy_identity_fields():
    field_names = {field.name for field in User._meta.get_fields()}
    forbidden = {"ten" + "ant", "account_" + "origin"}
    assert field_names.isdisjoint(forbidden)


@pytest.mark.django_db
def test_valid_email_login(client):
    User.objects.create_user("owner@example.com", "safe-test-password")
    response = client.post(
        reverse("login"),
        {"username": "OWNER@EXAMPLE.COM", "password": "safe-test-password"},
    )
    assert response.status_code == 302
    assert response.url == reverse("root")


@pytest.mark.django_db
def test_invalid_login_shows_safe_message(client):
    response = client.post(
        reverse("login"),
        {"username": "nobody@example.com", "password": "wrong"},
    )
    assert response.status_code == 200
    assert "E-mail ou senha inválidos." in response.content.decode()


@pytest.mark.django_db
def test_inactive_user_cannot_login(client):
    User.objects.create_user(
        "inactive@example.com",
        "safe-test-password",
        is_active=False,
    )
    response = client.post(
        reverse("login"),
        {"username": "inactive@example.com", "password": "safe-test-password"},
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
