import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.organizations.models import Membership, Organization

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_root_redirects_to_login(client):
    response = client.get(reverse("root"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_authenticated_root_redirects_to_organizations(client):
    user = User.objects.create_user("owner@example.com")
    client.force_login(user)
    response = client.get(reverse("root"))
    assert response.status_code == 302
    assert response.url == reverse("organizations:list")


@pytest.mark.django_db
def test_user_without_membership_is_handled_safely(client):
    user = User.objects.create_user("owner@example.com")
    client.force_login(user)
    response = client.get(reverse("organizations:list"))
    assert response.status_code == 200
    assert "ainda não possui acesso ativo" in response.content.decode()


@pytest.mark.django_db
def test_customer_and_product_routes_exist_for_authenticated_member(client):
    user = User.objects.create_user("owner@example.com")
    organization = Organization.objects.create(name="Org", slug="org")
    Membership.objects.create(organization=organization, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    assert client.get(reverse("customers:list")).status_code == 200
    assert client.get(reverse("customers:create")).status_code == 200
    assert client.get(reverse("products:list")).status_code == 200
    assert client.get(reverse("products:create")).status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/api/v1/customers/", "/api/v1/products/"],
)
def test_domain_api_is_not_exposed_in_phase_two(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.django_db
def test_logout_requires_post_and_ends_session(client):
    user = User.objects.create_user("owner@example.com")
    organization = Organization.objects.create(name="Org", slug="org")
    Membership.objects.create(organization=organization, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    assert client.get(reverse("logout")).status_code == 405
    assert client.post(reverse("logout")).status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize(
    "path",
    [
        "/clientes-v2/",
        "/pedidos-v2/",
        "/marketing/",
        "/restock/",
    ],
)
def test_known_legacy_routes_do_not_exist(client, path):
    assert client.get(path).status_code == 404


def test_native_integrations_route_exists_and_requires_authentication(client):
    response = client.get("/integrations/")
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
