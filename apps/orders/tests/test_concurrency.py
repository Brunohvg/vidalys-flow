import threading
import uuid

import pytest
from django.db import close_old_connections

from apps.customers.models import Customer
from apps.customers.services import merge_customers
from apps.orders import services as order_services
from apps.orders.exceptions import InvalidTransition, VersionConflict
from apps.orders.models import Order, OrderCommandReceipt, OrderNumberSequence, OrderStatusHistory
from apps.orders.services import add_item, cancel_order, confirm_order, create_order
from apps.products.models import Product, ProductVariant
from apps.products.services import create_product, create_variant, set_product_status


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


@pytest.mark.django_db(transaction=True)
def test_confirmation_serializes_against_customer_merge(
    organization,
    user,
    operator_membership,
    manager,
    manager_membership,
    monkeypatch,
):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente de origem",
    )
    canonical = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente canônico",
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
    source_validated = threading.Event()
    release_confirmation = threading.Event()
    merge_finished = threading.Event()
    errors = []
    original_require_customer = order_services._require_customer

    def pause_after_customer_validation(*, organization, customer):
        original_require_customer(organization=organization, customer=customer)
        source_validated.set()
        if not release_confirmation.wait(timeout=5):
            raise TimeoutError("Confirmação não foi liberada pelo teste.")

    monkeypatch.setattr(order_services, "_require_customer", pause_after_customer_validation)

    def confirm_worker():
        close_old_connections()
        try:
            confirm_order(
                organization=organization,
                order=Order.objects.get(id=order.id),
                actor=user,
                expected_version=2,
                idempotency_key=str(uuid.uuid4()),
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            close_old_connections()

    def merge_worker():
        close_old_connections()
        try:
            merge_customers(
                organization=organization,
                source=Customer.objects.get(id=customer.id),
                target=Customer.objects.get(id=canonical.id),
                actor=manager,
                reason="Duplicidade confirmada",
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            merge_finished.set()
            close_old_connections()

    confirmation = threading.Thread(target=confirm_worker)
    confirmation.start()
    assert source_validated.wait(timeout=5)
    merge = threading.Thread(target=merge_worker)
    merge.start()
    assert not merge_finished.wait(timeout=0.3)
    release_confirmation.set()
    confirmation.join(timeout=10)
    merge.join(timeout=10)

    order.refresh_from_db()
    customer.refresh_from_db()
    assert not errors
    assert order.status == Order.Status.CONFIRMED
    assert order.customer_name_snapshot == "Cliente de origem"
    assert customer.merged_into_id == canonical.id


def _catalog_order(*, organization, user):
    customer = Customer.objects.create(
        organization=organization,
        customer_type=Customer.Type.INDIVIDUAL,
        display_name="Cliente catálogo",
    )
    product = create_product(organization=organization, actor=user, name="Produto atual")
    variant = create_variant(
        organization=organization,
        product=product,
        actor=user,
        name="Variação atual",
        sku="VAR-ATUAL",
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
        product=product,
        variant=variant,
        quantity=1,
        unit_price=10,
    )
    return order, product, variant


@pytest.mark.django_db(transaction=True)
def test_confirmation_serializes_against_product_inactivation(
    organization,
    user,
    operator_membership,
    monkeypatch,
):
    order, product, _ = _catalog_order(organization=organization, user=user)
    source_validated = threading.Event()
    release_confirmation = threading.Event()
    update_finished = threading.Event()
    errors = []
    original_validate = order_services._validate_catalog_item

    def pause_after_catalog_validation(**kwargs):
        result = original_validate(**kwargs)
        source_validated.set()
        if not release_confirmation.wait(timeout=5):
            raise TimeoutError("Confirmação não foi liberada pelo teste.")
        return result

    monkeypatch.setattr(order_services, "_validate_catalog_item", pause_after_catalog_validation)

    def confirm_worker():
        close_old_connections()
        try:
            confirm_order(
                organization=organization,
                order=Order.objects.get(id=order.id),
                actor=user,
                expected_version=2,
                idempotency_key=str(uuid.uuid4()),
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            close_old_connections()

    def update_worker():
        close_old_connections()
        try:
            set_product_status(
                organization=organization,
                product=Product.objects.get(id=product.id),
                actor=user,
                status=Product.Status.INACTIVE,
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            update_finished.set()
            close_old_connections()

    confirmation = threading.Thread(target=confirm_worker)
    confirmation.start()
    assert source_validated.wait(timeout=5)
    update = threading.Thread(target=update_worker)
    update.start()
    assert not update_finished.wait(timeout=0.3)
    release_confirmation.set()
    confirmation.join(timeout=10)
    update.join(timeout=10)

    order.refresh_from_db()
    product.refresh_from_db()
    assert not errors
    assert order.status == Order.Status.CONFIRMED
    assert product.status == Product.Status.INACTIVE


@pytest.mark.django_db(transaction=True)
def test_confirmation_serializes_against_variant_inactivation(
    organization,
    user,
    operator_membership,
    monkeypatch,
):
    order, _, variant = _catalog_order(organization=organization, user=user)
    source_validated = threading.Event()
    release_confirmation = threading.Event()
    update_finished = threading.Event()
    errors = []
    original_validate = order_services._validate_catalog_item

    def pause_after_catalog_validation(**kwargs):
        result = original_validate(**kwargs)
        source_validated.set()
        if not release_confirmation.wait(timeout=5):
            raise TimeoutError("Confirmação não foi liberada pelo teste.")
        return result

    monkeypatch.setattr(order_services, "_validate_catalog_item", pause_after_catalog_validation)

    def confirm_worker():
        close_old_connections()
        try:
            confirm_order(
                organization=organization,
                order=Order.objects.get(id=order.id),
                actor=user,
                expected_version=2,
                idempotency_key=str(uuid.uuid4()),
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            close_old_connections()

    def update_worker():
        close_old_connections()
        try:
            ProductVariant.objects.filter(id=variant.id).update(status=Product.Status.INACTIVE)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            update_finished.set()
            close_old_connections()

    confirmation = threading.Thread(target=confirm_worker)
    confirmation.start()
    assert source_validated.wait(timeout=5)
    update = threading.Thread(target=update_worker)
    update.start()
    assert not update_finished.wait(timeout=0.3)
    release_confirmation.set()
    confirmation.join(timeout=10)
    update.join(timeout=10)

    order.refresh_from_db()
    variant.refresh_from_db()
    assert not errors
    assert order.status == Order.Status.CONFIRMED
    assert variant.status == Product.Status.INACTIVE
