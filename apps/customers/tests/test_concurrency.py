from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connections

from apps.customers.exceptions import InvalidMergeError
from apps.customers.models import Customer, CustomerMerge
from apps.customers.services import create_customer, merge_customers


@pytest.mark.django_db(transaction=True)
def test_concurrent_merge_of_same_source_only_succeeds_once(
    organization,
    manager,
    manager_membership,
):
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
    barrier = Barrier(2)

    def attempt_merge():
        close_old_connections()
        barrier.wait()
        try:
            merge_customers(
                organization=type(organization).objects.get(id=organization.id),
                source=Customer.objects.get(id=source.id),
                target=Customer.objects.get(id=target.id),
                actor=type(manager).objects.get(id=manager.id),
                reason="Concorrência",
            )
        except InvalidMergeError:
            return "rejected"
        finally:
            connections.close_all()
        return "merged"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt_merge(), range(2)))

    assert sorted(results) == ["merged", "rejected"]
    assert CustomerMerge.objects.filter(source_customer_id=source.id).count() == 1
