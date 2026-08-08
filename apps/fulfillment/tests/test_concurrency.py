import threading
import uuid

import pytest
from django.db import close_old_connections

from apps.fulfillment.exceptions import InvalidFulfillment
from apps.fulfillment.models import Fulfillment
from apps.fulfillment.services import create_fulfillment
from apps.orders.models import Order, OrderItem
from apps.organizations.models import Organization
from apps.users.models import User


@pytest.mark.django_db(transaction=True)
def test_concurrent_partial_allocations_never_exceed_order_quantity(
    organization, confirmed_order, confirmed_item, user, operator_membership
):
    barrier = threading.Barrier(2)
    successes = []
    expected_errors = []
    unexpected_errors = []

    def worker():
        close_old_connections()
        try:
            local_organization = Organization.objects.get(id=organization.id)
            local_order = Order.objects.get(id=confirmed_order.id)
            local_item = OrderItem.objects.get(id=confirmed_item.id)
            local_user = User.objects.get(id=user.id)
            barrier.wait(timeout=5)
            created = create_fulfillment(
                organization=local_organization,
                order=local_order,
                actor=local_user,
                method="delivery",
                allocations=[{"order_item": local_item, "quantity": 6}],
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append(created.id)
        except InvalidFulfillment as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not unexpected_errors
    assert len(successes) == 1
    assert len(expected_errors) == 1
    assert Fulfillment.objects.count() == 1
