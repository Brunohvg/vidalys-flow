from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import constant_time_compare, salted_hmac

from apps.fulfillment import policies, services
from apps.fulfillment.exceptions import FulfillmentPermissionDenied, InvalidFulfillment
from apps.fulfillment.models import Fulfillment

PICKUP_CODE_DIGITS = 6
PICKUP_MAX_ATTEMPTS = 5
PICKUP_ATTEMPT_WINDOW_SECONDS = 600


def _require_ready_pickup(*, fulfillment):
    if fulfillment.method != Fulfillment.Method.PICKUP:
        raise InvalidFulfillment("O fulfillment não é uma retirada.")
    if fulfillment.status != Fulfillment.Status.READY or fulfillment.ready_at is None:
        raise InvalidFulfillment("A retirada precisa estar pronta antes da validação.")


def pickup_verification_code(*, fulfillment):
    """Derive a short code without persisting or logging the customer credential."""

    _require_ready_pickup(fulfillment=fulfillment)
    material = ":".join(
        (
            str(fulfillment.organization_id),
            str(fulfillment.id),
            str(fulfillment.version),
            fulfillment.ready_at.isoformat(),
        )
    )
    digest = salted_hmac("vidalys.fulfillment.pickup-code.v1", material).hexdigest()
    value = int(digest[:16], 16) % (10**PICKUP_CODE_DIGITS)
    return f"{value:0{PICKUP_CODE_DIGITS}d}"


def _attempt_key(*, organization, fulfillment, actor):
    return f"pickup-verify:{organization.id}:{fulfillment.id}:{actor.id}"


def _consume_attempt(*, organization, fulfillment, actor):
    key = _attempt_key(organization=organization, fulfillment=fulfillment, actor=actor)
    try:
        if cache.add(key, 1, timeout=PICKUP_ATTEMPT_WINDOW_SECONDS):
            return key
        attempts = cache.incr(key)
    except Exception as exc:
        raise ImproperlyConfigured("Rate limit de retirada indisponível; validação bloqueada.") from exc
    if attempts > PICKUP_MAX_ATTEMPTS:
        raise InvalidFulfillment("Muitas tentativas de código. Aguarde antes de tentar novamente.")
    return key


def reveal_pickup_code(*, organization, fulfillment, actor):
    if not policies.can_cancel_fulfillments(user=actor, organization=organization):
        raise FulfillmentPermissionDenied("Somente gerência pode consultar o código para comunicação ao cliente.")
    if fulfillment.organization_id != organization.id:
        raise InvalidFulfillment("Retirada não pertence à organização.")
    return pickup_verification_code(fulfillment=fulfillment)


def complete_pickup_with_code(
    *,
    organization,
    fulfillment,
    actor,
    code,
    expected_version,
    idempotency_key,
):
    if not policies.can_operate_fulfillments(user=actor, organization=organization):
        raise FulfillmentPermissionDenied("Membership ativa é obrigatória.")
    if fulfillment.organization_id != organization.id or fulfillment.order.organization_id != organization.id:
        raise InvalidFulfillment("Retirada não pertence à organização.")
    _require_ready_pickup(fulfillment=fulfillment)

    rate_key = _consume_attempt(
        organization=organization,
        fulfillment=fulfillment,
        actor=actor,
    )
    expected_code = pickup_verification_code(fulfillment=fulfillment)
    supplied_code = (code or "").strip()
    if not constant_time_compare(supplied_code, expected_code):
        raise InvalidFulfillment("Código de retirada inválido.")

    result = services.transition_fulfillment(
        organization=organization,
        fulfillment=fulfillment,
        actor=actor,
        target_status=Fulfillment.Status.COMPLETED,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        _pickup_verified=True,
    )
    cache.delete(rate_key)
    return result
