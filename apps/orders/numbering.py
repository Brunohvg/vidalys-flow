from django.db import IntegrityError, transaction

from apps.orders.models import OrderNumberSequence


def allocate_order_number(*, organization):
    try:
        sequence = OrderNumberSequence.objects.select_for_update().get(organization=organization)
    except OrderNumberSequence.DoesNotExist:
        try:
            with transaction.atomic():
                OrderNumberSequence.objects.create(organization=organization)
        except IntegrityError:
            # A concurrent transaction created the organization's first
            # sequence. The unique organization constraint is authoritative.
            pass
        sequence = OrderNumberSequence.objects.select_for_update().get(organization=organization)
    number = sequence.next_number
    sequence.next_number += 1
    sequence.save(update_fields=("next_number", "updated_at"))
    return number
