from apps.orders.exceptions import InvalidTransition
from apps.orders.models import Order

ALLOWED_TRANSITIONS = {
    Order.Status.DRAFT: {Order.Status.CONFIRMED, Order.Status.CANCELLED},
    Order.Status.CONFIRMED: {Order.Status.CANCELLED},
    Order.Status.CANCELLED: set(),
}


def ensure_transition(*, from_status, to_status):
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise InvalidTransition(f"Transição inválida de {from_status} para {to_status}.")
