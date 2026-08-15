import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_authenticated_shell_keeps_primary_navigation_and_marks_current_page(
    client,
    user,
    operator_membership,
):
    client.force_login(user)

    response = client.get(reverse("orders:list"))
    html = response.content.decode()

    assert response.status_code == 200
    for section in ("Visão geral", "Operação", "Cadastros", "Comunicação", "Análise"):
        assert section in html
    for label in (
        "Dashboard",
        "Pedidos",
        "Retiradas",
        "Fulfillment",
        "Pagamentos",
        "Clientes",
        "Produtos",
        "Mensagens",
        "Integrações",
        "Relatórios",
        "Meu perfil",
        "Configurações",
        "Organizações",
    ):
        assert label in html
    assert f'href="{reverse("orders:list")}" aria-current="page"' in html


def test_dashboard_report_marks_reports_not_dashboard_as_current(
    client,
    user,
    operator_membership,
):
    client.force_login(user)

    response = client.get(reverse("dashboard:order-report"))
    html = response.content.decode()

    assert response.status_code == 200
    assert f'href="{reverse("dashboard:order-report")}" aria-current="page"' in html
    assert f'href="{reverse("dashboard:home")}" aria-current="page"' not in html
