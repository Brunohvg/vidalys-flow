from apps.fulfillment.exceptions import InvalidTransition
from apps.fulfillment.models import Fulfillment

ALLOWED_TRANSITIONS = {
    Fulfillment.Status.DRAFT: {Fulfillment.Status.PREPARING, Fulfillment.Status.CANCELLED},
    Fulfillment.Status.PREPARING: {Fulfillment.Status.READY, Fulfillment.Status.CANCELLED},
    Fulfillment.Status.READY: {
        Fulfillment.Status.IN_TRANSIT,
        Fulfillment.Status.COMPLETED,
        Fulfillment.Status.CANCELLED,
    },
    Fulfillment.Status.IN_TRANSIT: {Fulfillment.Status.COMPLETED, Fulfillment.Status.CANCELLED},
    Fulfillment.Status.COMPLETED: set(),
    Fulfillment.Status.CANCELLED: set(),
}


def ensure_transition(*, fulfillment, target_status):
    if target_status not in ALLOWED_TRANSITIONS.get(fulfillment.status, set()):
        raise InvalidTransition(f"Transição inválida: {fulfillment.status} → {target_status}.")
    if fulfillment.method == Fulfillment.Method.PICKUP and target_status == Fulfillment.Status.IN_TRANSIT:
        raise InvalidTransition("Retirada não pode entrar em trânsito.")
    if (
        fulfillment.method == Fulfillment.Method.DELIVERY
        and fulfillment.status == Fulfillment.Status.READY
        and target_status == Fulfillment.Status.COMPLETED
    ):
        raise InvalidTransition("Entrega deve ser despachada antes da conclusão.")
