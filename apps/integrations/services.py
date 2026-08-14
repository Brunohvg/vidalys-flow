import hashlib
import json
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.platform.services import enqueue_event

from .adapters import get_adapter
from .exceptions import (
    IntegrationAmbiguousError,
    IntegrationContractError,
    IntegrationPermanentError,
    IntegrationTransientError,
)
from .models import (
    IntegrationConnection,
    IntegrationDelivery,
    IntegrationDeliveryAttempt,
    IntegrationEndpoint,
    IntegrationReconciliationRun,
    IntegrationWebhookReceipt,
)

MAX_FAILURES_BEFORE_DEGRADED = 3
MAX_ATTEMPTS = 3
LEASE_SECONDS = 90
ALLOWED_PAYLOAD_KEYS = {
    "scenario",
    "reconcile_scenario",
    "subject",
    "state",
    "version",
    "reason_code",
    "external_ref",
}
ALLOWED_PAYLOAD_SCALARS = (str, int, float, bool, type(None))


def _canonical_payload(payload: dict) -> tuple[dict, str]:
    if not isinstance(payload, dict):
        raise IntegrationContractError("payload must be an object")
    unknown = set(payload) - ALLOWED_PAYLOAD_KEYS
    if unknown:
        raise IntegrationContractError("payload contains non-allowlisted fields")
    minimized = {str(k): v for k, v in payload.items() if isinstance(v, ALLOWED_PAYLOAD_SCALARS)}
    if len(minimized) != len(payload):
        raise IntegrationContractError("payload values must be scalar")
    encoded = json.dumps(minimized, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return minimized, hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def create_delivery(
    *,
    organization,
    endpoint,
    source_type,
    source_id,
    source_version,
    operation_key,
    idempotency_key,
    payload,
):
    if endpoint.organization_id != organization.id or endpoint.connection.organization_id != organization.id:
        raise IntegrationContractError("cross-organization endpoint")
    if not endpoint.is_active or endpoint.direction != IntegrationEndpoint.Direction.EGRESS:
        raise IntegrationContractError("egress endpoint is inactive")
    minimized, digest = _canonical_payload(payload)
    delivery, created = IntegrationDelivery.objects.get_or_create(
        organization=organization,
        idempotency_key=idempotency_key,
        defaults={
            "connection": endpoint.connection,
            "endpoint": endpoint,
            "source_type": source_type,
            "source_id": str(source_id),
            "source_version": source_version,
            "contract_version": endpoint.contract_version,
            "operation_key": operation_key,
            "payload_digest": digest,
            "payload": minimized,
            "status": IntegrationDelivery.Status.QUEUED,
        },
    )
    if delivery.payload_digest != digest:
        raise IntegrationContractError("idempotency key reused with different payload")
    if created:
        enqueue_event(
            organization=organization,
            event_type="integration.delivery.queued",
            aggregate_type="IntegrationDelivery",
            aggregate_id=delivery.id,
            payload={"delivery_id": str(delivery.id), "operation_key": operation_key},
            idempotency_key=f"integration-delivery:{delivery.id}:queued",
            event_contract_version=1,
        )
    return delivery


@transaction.atomic
def claim_delivery(delivery_id):
    delivery = (
        IntegrationDelivery.objects.select_for_update()
        .select_related("connection", "endpoint")
        .get(id=delivery_id)
    )
    if delivery.status not in {IntegrationDelivery.Status.QUEUED, IntegrationDelivery.Status.FAILED}:
        return None
    if delivery.next_attempt_at and delivery.next_attempt_at > timezone.now():
        return None
    if delivery.connection.status not in {IntegrationConnection.Status.ACTIVE, IntegrationConnection.Status.DEGRADED}:
        return None
    prior = delivery.attempts.count()
    if prior >= MAX_ATTEMPTS:
        return None
    attempt = IntegrationDeliveryAttempt.objects.create(
        organization=delivery.organization,
        delivery=delivery,
        sequence=prior + 1,
        status=IntegrationDeliveryAttempt.Status.SENDING,
        lease_token=secrets.token_hex(16),
        lease_expires_at=timezone.now() + timedelta(seconds=LEASE_SECONDS),
    )
    delivery.status = IntegrationDelivery.Status.SENDING
    delivery.next_attempt_at = None
    delivery.save(update_fields=("status", "next_attempt_at", "updated_at"))
    return attempt.id


def dispatch_delivery(delivery_id):
    attempt_id = claim_delivery(delivery_id)
    if not attempt_id:
        return None
    attempt = IntegrationDeliveryAttempt.objects.select_related("delivery__connection").get(id=attempt_id)
    delivery = attempt.delivery
    adapter = get_adapter(delivery.connection.adapter_key)
    try:
        result = adapter.send(payload=delivery.payload, idempotency_key=delivery.idempotency_key)
    except IntegrationAmbiguousError:
        return _finish_attempt(attempt_id, uncertain=True)
    except IntegrationTransientError:
        return _finish_attempt(attempt_id, failed=True, retryable=True)
    except IntegrationPermanentError:
        return _finish_attempt(attempt_id, failed=True, retryable=False)
    return _finish_attempt(attempt_id, external_id=result.external_id, result_code=result.result_code)


@transaction.atomic
def _finish_attempt(
    attempt_id,
    *,
    external_id="",
    result_code="",
    failed=False,
    retryable=False,
    uncertain=False,
):
    attempt = (
        IntegrationDeliveryAttempt.objects.select_for_update()
        .select_related("delivery__connection")
        .get(id=attempt_id)
    )
    delivery = IntegrationDelivery.objects.select_for_update().get(id=attempt.delivery_id)
    connection = IntegrationConnection.objects.select_for_update().get(id=delivery.connection_id)
    attempt.external_id = external_id
    attempt.result_code = result_code
    attempt.retryable = retryable
    attempt.lease_token = ""
    attempt.lease_expires_at = None
    if uncertain:
        attempt.status = IntegrationDeliveryAttempt.Status.UNCERTAIN
        delivery.status = IntegrationDelivery.Status.UNCERTAIN
    elif failed:
        attempt.status = IntegrationDeliveryAttempt.Status.FAILED
        delivery.status = IntegrationDelivery.Status.FAILED
        connection.failure_count += 1
        if connection.failure_count >= MAX_FAILURES_BEFORE_DEGRADED:
            connection.status = IntegrationConnection.Status.DEGRADED
            connection.degraded_at = timezone.now()
        if retryable and attempt.sequence < MAX_ATTEMPTS:
            delivery.next_attempt_at = timezone.now() + timedelta(seconds=2**attempt.sequence)
    else:
        attempt.status = IntegrationDeliveryAttempt.Status.SUCCEEDED
        delivery.status = IntegrationDelivery.Status.SUCCEEDED
        connection.failure_count = 0
        connection.last_success_at = timezone.now()
        connection.degraded_at = None
        if connection.status == IntegrationConnection.Status.DEGRADED:
            connection.status = IntegrationConnection.Status.ACTIVE
    attempt.save()
    delivery.save()
    connection.save()
    return delivery


def ingest_webhook(*, connection, endpoint, external_event_id, contract_version, payload, authenticated):
    if not authenticated:
        raise IntegrationContractError("webhook authentication failed")
    if endpoint.connection_id != connection.id or endpoint.organization_id != connection.organization_id:
        raise IntegrationContractError("endpoint mismatch")
    if not endpoint.is_active or endpoint.direction != IntegrationEndpoint.Direction.INGRESS:
        raise IntegrationContractError("ingress endpoint is inactive")
    if contract_version != endpoint.contract_version:
        raise IntegrationContractError("contract version mismatch")
    _, digest = _canonical_payload(payload)
    receipt, created = IntegrationWebhookReceipt.objects.get_or_create(
        connection=connection,
        endpoint=endpoint,
        external_event_id=external_event_id,
        defaults={
            "organization": connection.organization,
            "contract_version": contract_version,
            "payload_digest": digest,
            "disposition": "accepted",
        },
    )
    if not created and receipt.payload_digest != digest:
        raise IntegrationContractError("event id reused with different payload")
    return receipt, created


def reconcile_delivery(delivery):
    run, _ = IntegrationReconciliationRun.objects.get_or_create(
        organization=delivery.organization,
        connection=delivery.connection,
        subject_key=f"delivery:{delivery.id}",
        cursor=str(delivery.updated_at.timestamp()),
        defaults={"delivery": delivery, "status": IntegrationReconciliationRun.Status.RUNNING},
    )
    if run.status != IntegrationReconciliationRun.Status.RUNNING:
        return run
    attempt = delivery.attempts.order_by("-sequence").first()
    adapter = get_adapter(delivery.connection.adapter_key)
    try:
        result = adapter.reconcile(
            external_id=attempt.external_id if attempt else "",
            payload=delivery.payload,
        )
    except IntegrationAmbiguousError:
        run.status = IntegrationReconciliationRun.Status.UNCERTAIN
    except IntegrationPermanentError:
        run.status = IntegrationReconciliationRun.Status.FAILED
    else:
        run.status = IntegrationReconciliationRun.Status.SUCCEEDED
        run.result_code = result.result_code
        if delivery.status == IntegrationDelivery.Status.UNCERTAIN:
            delivery.status = IntegrationDelivery.Status.SUCCEEDED
            delivery.save(update_fields=("status", "updated_at"))
    run.save()
    return run
