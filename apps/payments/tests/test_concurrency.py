import threading
import uuid

import pytest
from django.db import close_old_connections, connections

from apps.organizations.models import Organization
from apps.payments.exceptions import InvalidPayment, VersionConflict
from apps.payments.models import PaymentIntent, PaymentProviderAccount
from apps.payments.services import create_payment_intent, request_hosted_checkout
from apps.users.models import User


@pytest.mark.django_db(transaction=True)
def test_concurrent_checkout_requests_produce_only_one_active_attempt(
    organization, payable_order, mercado_account, manager, manager_membership
):
    intent = create_payment_intent(
        organization=organization,
        order=payable_order,
        actor=manager,
        idempotency_key=str(uuid.uuid4()),
    )
    barrier = threading.Barrier(2)
    successes = []
    expected_errors = []
    unexpected_errors = []

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            attempt = request_hosted_checkout(
                organization=Organization.objects.get(id=organization.id),
                intent=PaymentIntent.objects.get(id=intent.id),
                provider_account=PaymentProviderAccount.objects.get(id=mercado_account.id),
                actor=User.objects.get(id=manager.id),
                expected_version=1,
                idempotency_key=str(uuid.uuid4()),
            )
            successes.append(attempt.id)
        except (InvalidPayment, VersionConflict) as exc:
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
    assert intent.attempts.filter(status="requested").count() == 1
