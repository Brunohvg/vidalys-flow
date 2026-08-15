from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.fulfillment import selectors
from apps.fulfillment.exceptions import FulfillmentDomainError
from apps.fulfillment.pickup_forms import PickupCompletionForm
from apps.fulfillment.pickup_services import complete_pickup_with_code
from apps.organizations.selectors import active_organization_for_user


@login_required
@require_POST
def complete_pickup(request, fulfillment_id):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or membership is None:
        raise Http404

    fulfillment = selectors.fulfillment_for_organization(
        organization=organization,
        fulfillment_id=fulfillment_id,
    )
    if fulfillment is None:
        raise Http404

    form = PickupCompletionForm(request.POST, fulfillment=fulfillment)
    if not form.is_valid():
        messages.error(request, "Código de retirada inválido.")
        return redirect("orders:detail", order_id=fulfillment.order_id)

    try:
        complete_pickup_with_code(
            organization=organization,
            fulfillment=fulfillment,
            actor=request.user,
            **form.cleaned_data,
        )
    except ImproperlyConfigured:
        messages.error(request, "Validação de retirada temporariamente indisponível.")
    except FulfillmentDomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Retirada confirmada.")
    return redirect("orders:detail", order_id=fulfillment.order_id)
