from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.fulfillment import policies, selectors, services, tracking_services
from apps.fulfillment.exceptions import FulfillmentDomainError
from apps.fulfillment.forms import TrackingForm, TransitionForm
from apps.fulfillment.models import Fulfillment
from apps.organizations.selectors import active_organization_for_user


def _context_or_404(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or membership is None:
        raise Http404
    if not policies.can_operate_fulfillments(user=request.user, organization=organization):
        raise Http404
    return organization


def _fulfillment_or_404(*, organization, fulfillment_id):
    fulfillment = selectors.fulfillment_for_organization(
        organization=organization,
        fulfillment_id=fulfillment_id,
    )
    if fulfillment is None:
        raise Http404
    return fulfillment


def _back_to_order(fulfillment):
    return redirect("orders:detail", order_id=fulfillment.order_id)


@login_required
@require_POST
def workspace_transition(request, fulfillment_id, target_status):
    organization = _context_or_404(request)
    fulfillment = _fulfillment_or_404(organization=organization, fulfillment_id=fulfillment_id)
    valid_targets = {choice for choice, _ in Fulfillment.Status.choices} - {
        Fulfillment.Status.DRAFT,
        Fulfillment.Status.CANCELLED,
    }
    if target_status not in valid_targets:
        raise Http404
    if (
        fulfillment.method == Fulfillment.Method.PICKUP
        and fulfillment.status == Fulfillment.Status.READY
        and target_status == Fulfillment.Status.COMPLETED
    ):
        messages.error(request, "Retirada pronta exige validação do código do cliente.")
        return _back_to_order(fulfillment)

    form = TransitionForm(request.POST)
    if form.is_valid():
        try:
            services.transition_fulfillment(
                organization=organization,
                fulfillment=fulfillment,
                actor=request.user,
                target_status=target_status,
                **form.cleaned_data,
            )
        except (FulfillmentDomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Atendimento atualizado no pedido.")
    else:
        messages.error(request, "Comando de atendimento inválido.")
    return _back_to_order(fulfillment)


@login_required
@require_POST
def workspace_tracking(request, fulfillment_id):
    organization = _context_or_404(request)
    fulfillment = _fulfillment_or_404(organization=organization, fulfillment_id=fulfillment_id)
    form = TrackingForm(request.POST)
    if form.is_valid():
        try:
            tracking_services.set_tracking(
                organization=organization,
                fulfillment=fulfillment,
                actor=request.user,
                **form.cleaned_data,
            )
        except (FulfillmentDomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Rastreio atualizado no pedido.")
    else:
        messages.error(request, "Revise o código ou link de rastreio.")
    return _back_to_order(fulfillment)
