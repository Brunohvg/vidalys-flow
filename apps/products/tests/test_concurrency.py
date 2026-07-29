from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connections

from apps.products.exceptions import DuplicateSkuError
from apps.products.models import Product, ProductVariant
from apps.products.services import create_product, create_variant


@pytest.mark.django_db(transaction=True)
def test_concurrent_variant_creation_preserves_sku_uniqueness(
    organization,
    user,
    operator_membership,
):
    first = create_product(organization=organization, actor=user, name="Primeiro")
    second = create_product(organization=organization, actor=user, name="Segundo")
    barrier = Barrier(2)

    def attempt(product_id):
        close_old_connections()
        barrier.wait()
        try:
            create_variant(
                organization=type(organization).objects.get(id=organization.id),
                product=Product.objects.get(id=product_id),
                actor=type(user).objects.get(id=user.id),
                sku="SKU-CONCORRENTE",
            )
        except DuplicateSkuError:
            return "rejected"
        finally:
            connections.close_all()
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (first.id, second.id)))

    assert sorted(results) == ["created", "rejected"]
    assert ProductVariant.objects.filter(organization=organization, sku="SKU-CONCORRENTE").count() == 1
