import pytest
from django.urls import reverse

from apps.customers.models import ContactPoint, Customer, CustomerAddress, CustomerMerge, CustomerNote
from apps.customers.services import create_customer
from apps.organizations.models import Membership


@pytest.mark.django_db
def test_customer_pages_require_authentication(client):
    assert client.get(reverse("customers:list")).status_code == 302


@pytest.mark.django_db
def test_list_and_detail_are_scoped_to_active_organization(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    visible = create_customer(
        organization=organization,
        actor=user,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Visível",
    )
    hidden = Customer.objects.create(
        organization=other_organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Oculto",
    )
    client.force_login(user)
    response = client.get(reverse("customers:list"))
    assert response.status_code == 200
    assert "Visível" in response.content.decode()
    assert "Oculto" not in response.content.decode()
    assert client.get(reverse("customers:detail", args=(hidden.id,))).status_code == 404
    assert client.get(reverse("customers:detail", args=(visible.id,))).status_code == 200


@pytest.mark.django_db
def test_create_and_edit_customer_views(client, organization, user, operator_membership):
    client.force_login(user)
    response = client.post(
        reverse("customers:create"),
        {
            "customer_type": Customer.Type.INDIVIDUAL,
            "display_name": "Cliente Web",
            "document": "52998224725",
            "email": "web@example.com",
        },
    )
    customer = Customer.objects.get(display_name="Cliente Web")
    assert response.status_code == 302
    response = client.post(
        reverse("customers:edit", args=(customer.id,)),
        {
            "display_name": "Cliente Editado",
            "legal_name": "",
            "notes_summary": "Operacional",
        },
    )
    customer.refresh_from_db()
    assert response.status_code == 302
    assert customer.display_name == "Cliente Editado"


@pytest.mark.django_db
def test_inactive_membership_cannot_access_views(client, organization, user, operator_membership):
    operator_membership.is_active = False
    operator_membership.save(update_fields=("is_active",))
    client.force_login(user)
    response = client.get(reverse("customers:list"))
    assert response.status_code == 302
    assert response.url == reverse("organizations:list")


@pytest.mark.django_db
def test_customer_detail_masks_personal_data_for_operator(client, organization, user, operator_membership):
    customer = create_customer(
        organization=organization,
        actor=user,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Pessoa",
        document="52998224725",
        email="person@example.com",
    )
    client.force_login(user)
    content = client.get(reverse("customers:detail", args=(customer.id,))).content.decode()
    assert "52998224725" not in content
    assert "pe***@example.com" in content


@pytest.mark.django_db
def test_customer_detail_operations(client, organization, user, operator_membership):
    customer = create_customer(
        organization=organization,
        actor=user,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Pessoa",
    )
    client.force_login(user)
    assert client.post(
        reverse("customers:add-contact", args=(customer.id,)),
        {"kind": ContactPoint.Kind.PHONE, "value": "11999991234", "is_primary": "on"},
    ).status_code == 302
    assert client.post(
        reverse("customers:add-address", args=(customer.id,)),
        {
            "street": "Rua A",
            "city": "São Paulo",
            "state": "SP",
            "country": "BR",
            "is_default_shipping": "on",
        },
    ).status_code == 302
    assert client.post(
        reverse("customers:add-note", args=(customer.id,)),
        {"content": "Nota operacional"},
    ).status_code == 302
    assert client.post(
        reverse("customers:change-status", args=(customer.id,)),
        {"status": Customer.Status.INACTIVE, "reason": "Sem atividade"},
    ).status_code == 302
    customer.refresh_from_db()
    assert customer.status == Customer.Status.INACTIVE
    assert CustomerAddress.objects.filter(customer=customer).count() == 1
    assert CustomerNote.objects.filter(customer=customer).count() == 1


@pytest.mark.django_db
def test_customer_merge_view_for_manager(client, organization, manager, manager_membership):
    source = create_customer(
        organization=organization,
        actor=manager,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Origem",
    )
    target = create_customer(
        organization=organization,
        actor=manager,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Destino",
    )
    client.force_login(manager)
    response = client.post(
        reverse("customers:merge", args=(source.id,)),
        {"target_id": target.id, "reason": "Duplicidade confirmada"},
    )
    assert response.status_code == 302
    assert response.url == reverse("customers:detail", args=(target.id,))
    assert CustomerMerge.objects.filter(source_customer=source, target_customer=target).exists()


@pytest.mark.django_db
def test_select_organization_revalidates_membership(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    client.force_login(user)
    denied = client.post(reverse("organizations:select", args=(other_organization.id,)))
    assert denied.status_code == 404
    allowed = client.post(reverse("organizations:select", args=(organization.id,)))
    assert allowed.status_code == 302
    assert client.session["active_organization_id"] == str(organization.id)


@pytest.mark.django_db
def test_multiple_memberships_require_explicit_selection(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    Membership.objects.create(
        organization=other_organization,
        user=user,
        role=Membership.Role.OPERATOR,
    )
    client.force_login(user)
    response = client.get(reverse("customers:list"))
    assert response.status_code == 302
    assert response.url == reverse("organizations:list")


@pytest.mark.django_db
def test_customer_list_is_paginated_at_25(client, organization, user, operator_membership):
    Customer.objects.bulk_create(
        [
            Customer(
                organization=organization,
                customer_type=Customer.Type.INDIVIDUAL,
                display_name=f"Cliente {index:02}",
            )
            for index in range(26)
        ]
    )
    client.force_login(user)
    response = client.get(reverse("customers:list"))
    assert response.context["customers"].paginator.per_page == 25
    assert len(response.context["customers"]) == 25
    assert "Próxima" in response.content.decode()
