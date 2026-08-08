import threading
import uuid

import pytest
from django.db import close_old_connections, connections
from django.db.models import Sum

from apps.fulfillment.exceptions import InvalidFulfillment, VersionConflict
from apps.fulfillment.models import Fulfillment
from apps.fulfillment.services import (
    consume_order_cancelled_event,
    create_fulfillment,
    replace_allocations,
    transition_fulfillment,
)
from apps.orders.models import Order, OrderItem
from apps.orders.services import cancel_order
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
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not unexpected_errors
    assert len(successes) == 1
    assert len(expected_errors) == 1
    assert Fulfillment.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_allocation_replacement_and_creation_never_exceed_order_quantity(
    organization, confirmed_order, confirmed_item, user, operator_membership
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 4}],
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    successes = []
    expected_errors = []
    unexpected_errors = []

    def replace_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            replace_allocations(
                organization=Organization.objects.get(id=organization.id),
                fulfillment=Fulfillment.objects.get(id=fulfillment.id),
                actor=User.objects.get(id=user.id),
                allocations=[
                    {
                        "order_item": OrderItem.objects.get(id=confirmed_item.id),
                        "quantity": 8,
                    }
                ],
                expected_version=1,
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append("replace")
        except InvalidFulfillment as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            connections.close_all()

    def create_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            create_fulfillment(
                organization=Organization.objects.get(id=organization.id),
                order=Order.objects.get(id=confirmed_order.id),
                actor=User.objects.get(id=user.id),
                method="delivery",
                allocations=[
                    {
                        "order_item": OrderItem.objects.get(id=confirmed_item.id),
                        "quantity": 4,
                    }
                ],
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append("create")
        except InvalidFulfillment as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=replace_worker), threading.Thread(target=create_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    total = confirmed_item.fulfillment_items.exclude(fulfillment__status="cancelled").aggregate(
        value=Sum("quantity")
    )["value"]
    assert not unexpected_errors
    assert len(successes) == 1
    assert len(expected_errors) == 1
    assert total <= confirmed_item.quantity


@pytest.mark.django_db(transaction=True)
def test_concurrent_transition_and_manual_cancellation_are_serialized(
    organization,
    confirmed_order,
    confirmed_item,
    user,
    manager,
    operator_membership,
    manager_membership,
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 1}],
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    successes = []
    expected_errors = []
    unexpected_errors = []

    def worker(*, actor_id, target_status, reason=""):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            transition_fulfillment(
                organization=Organization.objects.get(id=organization.id),
                fulfillment=Fulfillment.objects.get(id=fulfillment.id),
                actor=User.objects.get(id=actor_id),
                target_status=target_status,
                reason=reason,
                expected_version=1,
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append(target_status)
        except (InvalidFulfillment, VersionConflict) as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=worker, kwargs={"actor_id": user.id, "target_status": "preparing"}),
        threading.Thread(
            target=worker,
            kwargs={"actor_id": manager.id, "target_status": "cancelled", "reason": "Operação concorrente"},
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not unexpected_errors
    assert len(successes) == 1
    assert len(expected_errors) == 1


@pytest.mark.django_db(transaction=True)
def test_order_cancellation_event_and_transition_use_the_same_lock_order(
    organization,
    confirmed_order,
    confirmed_item,
    user,
    manager,
    operator_membership,
    manager_membership,
):
    fulfillment = create_fulfillment(
        organization=organization,
        order=confirmed_order,
        actor=user,
        method="delivery",
        allocations=[{"order_item": confirmed_item, "quantity": 1}],
        idempotency_key=str(uuid.uuid4()),
    )
    cancel_order(
        organization=organization,
        order=confirmed_order,
        actor=manager,
        reason="Cancelamento comercial",
        expected_version=confirmed_order.version,
        idempotency_key=str(uuid.uuid4()),
    )
    event = organization.outbox_events.get(event_type="order.cancelled")
    barrier = threading.Barrier(2)
    consumed = []
    expected_errors = []
    unexpected_errors = []

    def transition_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            transition_fulfillment(
                organization=Organization.objects.get(id=organization.id),
                fulfillment=Fulfillment.objects.get(id=fulfillment.id),
                actor=User.objects.get(id=user.id),
                target_status="preparing",
                expected_version=1,
                idempotency_key=str(uuid.uuid4()),
            )
        except InvalidFulfillment as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            connections.close_all()

    def consume_worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            from apps.platform.models import OutboxEvent

            consumed.append(consume_order_cancelled_event(event=OutboxEvent.objects.get(id=event.id)))
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=transition_worker), threading.Thread(target=consume_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    fulfillment.refresh_from_db()
    assert not unexpected_errors
    assert len(expected_errors) == 1
    assert consumed == [1]
    assert fulfillment.status == Fulfillment.Status.CANCELLED
