import pytest
from django.urls import reverse

from apps.products.models import Product, ProductIdentifier
from apps.products.services import create_product


@pytest.mark.django_db
def test_product_pages_require_authentication(client):
    assert client.get(reverse("products:list")).status_code == 302


@pytest.mark.django_db
def test_list_and_detail_are_scoped_to_active_organization(
    client,
    organization,
    other_organization,
    user,
    operator_membership,
):
    visible = create_product(organization=organization, actor=user, name="Visível")
    hidden = Product.objects.create(organization=other_organization, name="Oculto")
    client.force_login(user)
    response = client.get(reverse("products:list"))
    assert response.status_code == 200
    assert "Visível" in response.content.decode()
    assert "Oculto" not in response.content.decode()
    assert client.get(reverse("products:detail", args=(hidden.id,))).status_code == 404
    assert client.get(reverse("products:detail", args=(visible.id,))).status_code == 200


@pytest.mark.django_db
def test_create_edit_and_variant_views(client, organization, user, operator_membership):
    client.force_login(user)
    response = client.post(
        reverse("products:create"),
        {"name": "Produto Web", "description": "", "default_unit": "UN"},
    )
    product = Product.objects.get(name="Produto Web")
    assert response.status_code == 302
    response = client.post(
        reverse("products:edit", args=(product.id,)),
        {"name": "Produto Editado", "description": "Detalhe", "default_unit": "pc"},
    )
    assert response.status_code == 302
    response = client.post(
        reverse("products:add-variant", args=(product.id,)),
        {"name": "Azul", "sku": " sku-blue ", "barcode": ""},
    )
    product.refresh_from_db()
    assert response.status_code == 302
    assert product.name == "Produto Editado"
    assert product.variants.get().sku == "SKU-BLUE"


@pytest.mark.django_db
def test_inactive_membership_cannot_access_product_views(
    client,
    organization,
    user,
    operator_membership,
):
    operator_membership.is_active = False
    operator_membership.save(update_fields=("is_active",))
    client.force_login(user)
    response = client.get(reverse("products:list"))
    assert response.status_code == 302
    assert response.url == reverse("organizations:list")


@pytest.mark.django_db
def test_identifier_and_status_views(client, organization, user, operator_membership):
    product = create_product(organization=organization, actor=user, name="Produto")
    client.force_login(user)
    response = client.post(
        reverse("products:add-identifier", args=(product.id,)),
        {"kind": ProductIdentifier.Kind.INTERNAL_CODE, "value": " ref-10 "},
    )
    assert response.status_code == 302
    assert product.identifiers.get().value == "REF-10"
    response = client.post(
        reverse("products:change-status", args=(product.id,)),
        {"status": Product.Status.INACTIVE, "reason": "Fora de linha"},
    )
    product.refresh_from_db()
    assert response.status_code == 302
    assert product.status == Product.Status.INACTIVE


@pytest.mark.django_db
def test_invalid_product_forms_do_not_mutate(client, organization, user, operator_membership):
    product = create_product(organization=organization, actor=user, name="Produto")
    client.force_login(user)
    assert client.post(reverse("products:add-variant", args=(product.id,)), {}).status_code == 302
    assert product.variants.count() == 1
    response = client.post(reverse("products:create"), {"name": "", "default_unit": "un"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_product_list_is_paginated_at_25(client, organization, user, operator_membership):
    Product.objects.bulk_create(
        [Product(organization=organization, name=f"Produto {index:02}") for index in range(26)]
    )
    client.force_login(user)
    response = client.get(reverse("products:list"))
    assert response.context["products"].paginator.per_page == 25
    assert len(response.context["products"]) == 25
    assert "Próxima" in response.content.decode()
