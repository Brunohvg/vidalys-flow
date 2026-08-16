import pytest
from django.urls import reverse

from apps.platform.xlsx import parse_xlsx

pytestmark = pytest.mark.django_db


def test_order_report_xlsx_is_downloadable_and_tabular(
    client,
    user,
    operator_membership,
):
    client.force_login(user)

    response = client.get(reverse("dashboard:order-report-xlsx"), {"period": "month"})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    headers, rows = parse_xlsx(response.content, max_rows=1000)
    assert headers == ("Data", "Quantidade de pedidos", "Valor dos pedidos")
    assert isinstance(rows, list)
