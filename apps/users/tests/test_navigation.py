import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_authenticated_shell_exposes_settings_hub_without_bypassing_view_permissions(
    client,
    user,
    operator_membership,
):
    client.force_login(user)

    response = client.get(reverse("users:profile"))

    assert response.status_code == 200
    html = response.content.decode()
    assert f'href="{reverse("users:settings")}"' in html
    assert ">Configurações</a>" in html
