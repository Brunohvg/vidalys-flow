import threading
import uuid

import pytest
from django.db import close_old_connections

from apps.customers.models import Customer
from apps.orders.exceptions import InvalidTransition, VersionConflict
from apps.orders.models import Order, OrderCommandReceipt, OrderNumberSequence, OrderStatusHistory
from apps.orders.services import add_item, cancel_order, confirm_order, create_order


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_sequence_creation_is_unique(organization, user, operator_membership):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Concorrente",
    )
    barrier = threading.Barrier(4)
    numbers = []
    errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            created = create_order(
                organization=organization,
                customer=customer,
                actor=user,
                idempotency_key=str(uuid.uuid4()),
            )
            numbers.append(created.number)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert sorted(numbers) == [1, 2, 3, 4]
    assert OrderNumberSequence.objects.filter(organization=organization).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_create_command_produces_one_order(organization, user, operator_membership):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Idempotente",
    )
    command_key = str(uuid.uuid4())
    barrier = threading.Barrier(2)
    ids = []
    errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            created = create_order(
                organization=organization,
                customer=customer,
                actor=user,
                idempotency_key=command_key,
            )
            ids.append(created.id)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert len(set(ids)) == 1
    assert Order.objects.count() == 1
    assert OrderCommandReceipt.objects.filter(operation="create_order").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_confirmation_only_one_distinct_command_wins(organization, user, operator_membership):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Confirmação",
    )
    order = create_order(
        organization=organization,
        customer=customer,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
    )
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    barrier = threading.Barrier(2)
    successes = []
    errors = []

    def worker():
        close_old_connections()
        try:
            local = Order.objects.get(id=order.id)
            barrier.wait(timeout=5)
            confirm_order(
                organization=organization,
                order=local,
                actor=user,
                expected_version=2,
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append(True)
        except (VersionConflict, InvalidTransition) as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(successes) == 1
    assert len(errors) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_confirmation_and_cancellation_only_one_transition_wins(
    organization,
    user,
    operator_membership,
    manager,
    manager_membership,
):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Transição concorrente",
    )
    order = create_order(
        organization=organization,
        customer=customer,
        actor=user,
        idempotency_key=str(uuid.uuid4()),
    )
    add_item(
        organization=organization,
        order=order,
        actor=user,
        expected_version=1,
        idempotency_key=str(uuid.uuid4()),
        name="Item",
        quantity=1,
        unit_price=10,
    )
    barrier = threading.Barrier(2)
    successes = []
    expected_errors = []
    unexpected_errors = []

    def worker(action, actor):
        close_old_connections()
        try:
            local = Order.objects.get(id=order.id)
            barrier.wait(timeout=5)
            if action == "confirm":
                confirm_order(
                    organization=organization,
                    order=local,
                    actor=actor,
                    expected_version=2,
                    idempotency_key=str(uuid.uuid4()),
                )
            else:
                cancel_order(
                    organization=organization,
                    order=local,
                    actor=actor,
                    reason="Cancelamento concorrente",
                    expected_version=2,
                    idempotency_key=str(uuid.uuid4()),
                )
            successes.append(action)
        except (VersionConflict, InvalidTransition) as exc:
            expected_errors.append(exc)
        except Exception as exc:  # pragma: no cover - asserted below
            unexpected_errors.append(exc)
        finally:
            close_old_connections()

    threads = [
        threading.Thread(target=worker, args=("confirm", user)),
        threading.Thread(target=worker, args=("cancel", manager)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    order.refresh_from_db()
    assert not unexpected_errors
    assert len(successes) == 1
    assert len(expected_errors) == 1
    assert order.status in {Order.Status.CONFIRMED, Order.Status.CANCELLED}
    assert order.version == 3
    assert OrderStatusHistory.objects.filter(order=order).count() == 2
