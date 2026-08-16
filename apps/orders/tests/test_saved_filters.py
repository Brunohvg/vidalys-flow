import uuid

import pytest
from django.urls import reverse

from apps.orders.saved_filter_views import SESSION_KEY

pytestmark = pytest.mark.django_db


def test_save_filter_normalizes_allowlisted_query_and_renders_it(
    client,
    organization,
    user,
    operator_membership,
):
    client.force_login(user)
    response = client.post(
        reverse("orders:save-filter"),
        {
            "name": "  Confirmados web  ",
            "querystring": "status=confirmed&channel=web&page=999&unexpected=secret",
        },
    )

    assert response.status_code == 302
    session = client.session
    entries = session[SESSION_KEY]
    assert len(entries) == 1
    assert entries[0]["organization_id"] == str(organization.id)
    assert entries[0]["name"] == "Confirmados web"
    assert "status=confirmed" in entries[0]["querystring"]
    assert "channel=web" in entries[0]["querystring"]
    assert "page=" not in entries[0]["querystring"]
    assert "unexpected=" not in entries[0]["querystring"]

    page = client.get(reverse("orders:list"))
    html = page.content.decode()
    assert "Confirmados web" in html
    assert entries[0]["querystring"] in html


def test_saved_filter_list_is_scoped_to_active_organization(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    client.force_login(user)
    session = client.session
    session[SESSION_KEY] = [
        {
            "id": str(uuid.uuid4()),
            "organization_id": str(organization.id),
            "name": "Visível",
            "querystring": "status=confirmed",
        },
        {
            "id": str(uuid.uuid4()),
            "organization_id": str(other_organization.id),
            "name": "Não deve aparecer",
            "querystring": "status=cancelled",
        },
    ]
    session.save()

    response = client.get(reverse("orders:list"))
    html = response.content.decode()
    assert "Visível" in html
    assert "Não deve aparecer" not in html


def test_delete_filter_only_removes_entry_from_active_organization(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    client.force_login(user)
    visible_id = uuid.uuid4()
    other_id = uuid.uuid4()
    session = client.session
    session[SESSION_KEY] = [
        {
            "id": str(visible_id),
            "organization_id": str(organization.id),
            "name": "Remover",
            "querystring": "status=draft",
        },
        {
            "id": str(other_id),
            "organization_id": str(other_organization.id),
            "name": "Preservar",
            "querystring": "status=cancelled",
        },
    ]
    session.save()

    response = client.post(reverse("orders:delete-filter", args=(visible_id,)))
    assert response.status_code == 302
    remaining = client.session[SESSION_KEY]
    assert [entry["id"] for entry in remaining] == [str(other_id)]
