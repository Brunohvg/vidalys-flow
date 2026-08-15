from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from apps.fulfillment.events import FULFILLMENT_UPDATED
from apps.fulfillment.exceptions import InvalidFulfillment
from apps.fulfillment.idempotency import claim_command, complete_command
from apps.fulfillment.models import Fulfillment
from apps.fulfillment.services import (
    _audit,
    _ensure_version,
    _existing_result,
    _lock_order_then_fulfillment,
    _outbox,
    _require_permission,
)

https_validator = URLValidator(schemes=("https",))


@transaction.atomic
def set_tracking(
    *,
    organization,
    fulfillment,
    actor,
    tracking_code,
    tracking_url,
    expected_version,
    idempotency_key,
):
    _require_permission(actor=actor, organization=organization)
    code = (tracking_code or "").strip()
    url = (tracking_url or "").strip()
    if len(code) > 120:
        raise InvalidFulfillment("Código de rastreio excede o limite permitido.")
    if url:
        try:
            https_validator(url)
        except ValidationError as exc:
            raise InvalidFulfillment("Link de rastreio deve ser uma URL HTTPS válida.") from exc

    payload = {
        "fulfillment_id": str(fulfillment.id),
        "expected_version": expected_version,
        "tracking_code": code,
        "tracking_url": url,
    }
    receipt, is_new = claim_command(
        organization=organization,
        operation="set_fulfillment_tracking",
        idempotency_key=idempotency_key,
        payload=payload,
        actor=actor,
    )
    if not is_new:
        return _existing_result(receipt)

    _, fulfillment = _lock_order_then_fulfillment(
        organization=organization,
        fulfillment=fulfillment,
    )
    _ensure_version(fulfillment=fulfillment, expected_version=expected_version)
    if fulfillment.method != Fulfillment.Method.DELIVERY:
        raise InvalidFulfillment("Rastreio só pode ser configurado para entrega.")
    if fulfillment.status not in {Fulfillment.Status.READY, Fulfillment.Status.IN_TRANSIT}:
        raise InvalidFulfillment("Rastreio só pode ser alterado quando a entrega está pronta ou em trânsito.")

    changed_fields = []
    if fulfillment.tracking_code != code:
        fulfillment.tracking_code = code
        changed_fields.append("tracking_code")
    if fulfillment.tracking_url != url:
        fulfillment.tracking_url = url
        changed_fields.append("tracking_url")
    if changed_fields:
        fulfillment.version += 1
        fulfillment.save(update_fields=(*changed_fields, "version", "updated_at"))
        _audit(
            fulfillment=fulfillment,
            actor=actor,
            action=FULFILLMENT_UPDATED,
            payload={
                "changed_fields": changed_fields,
                "tracking_configured": bool(code or url),
            },
        )
        _outbox(
            fulfillment=fulfillment,
            event_type=FULFILLMENT_UPDATED,
            command_id=idempotency_key,
        )
    complete_command(receipt=receipt, fulfillment=fulfillment)
    return fulfillment
