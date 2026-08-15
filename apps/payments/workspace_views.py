from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.orders.selectors import order_for_organization
from apps.organizations.selectors import active_organization_for_user
from apps.payments import policies, selectors, services
from apps.payments.exceptions import PaymentDomainError
from apps.payments.forms import CheckoutRequestForm, PaymentCommandForm, PaymentIntentCreateForm
from apps.payments.manual_forms import ManualPaymentForm
from apps.payments.manual_services import confirm_manual_payment


def _organization_for_manager(request):
    organization, _membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or not policies.can_operate_payments(user=request.user, organization=organization):
        raise Http404
    return organization


def _payment_or_404(*, organization, payment_id):
    payment = selectors.payment_for_organization(organization=organization, payment_id=payment_id)
    if payment is None:
        raise Http404
    return payment


def _back_to_order(order_id):
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def workspace_create_payment(request, order_id):
    organization = _organization_for_manager(request)
    order = order_for_organization(organization=organization, order_id=order_id)
    if order is None:
        raise Http404

    form = PaymentIntentCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Comando inválido para preparar o pagamento.")
        return _back_to_order(order.id)

    try:
        services.create_payment_intent(
            organization=organization,
            order=order,
            actor=request.user,
            idempotency_key=form.cleaned_data["idempotency_key"],
        )
    except PaymentDomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Pagamento preparado no pedido.")
    return _back_to_order(order.id)


@login_required
@require_POST
def workspace_confirm_manual(request, payment_id):
    organization = _organization_for_manager(request)
    payment = _payment_or_404(organization=organization, payment_id=payment_id)
    form = ManualPaymentForm(request.POST, payment=payment)
    if not form.is_valid():
        messages.error(request, "Confirmação manual inválida.")
        return _back_to_order(payment.order_id)

    try:
        confirm_manual_payment(
            organization=organization,
            intent=payment,
            actor=request.user,
            **form.cleaned_data,
        )
    except PaymentDomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Pagamento recebido confirmado no pedido.")
    return _back_to_order(payment.order_id)


@login_required
@require_POST
def workspace_request_checkout(request, payment_id):
    organization = _organization_for_manager(request)
    payment = _payment_or_404(organization=organization, payment_id=payment_id)
    form = CheckoutRequestForm(request.POST, organization=organization, payment=payment)
    if not form.is_valid():
        messages.error(request, "Comando de checkout inválido.")
        return _back_to_order(payment.order_id)

    try:
        services.request_hosted_checkout(
            organization=organization,
            intent=payment,
            actor=request.user,
            **form.cleaned_data,
        )
    except PaymentDomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Solicitação de checkout registrada no pedido, sem chamada externa.")
    return _back_to_order(payment.order_id)


@login_required
@require_POST
def workspace_cancel_checkout(request, payment_id):
    organization = _organization_for_manager(request)
    payment = _payment_or_404(organization=organization, payment_id=payment_id)
    form = PaymentCommandForm(request.POST, payment=payment)
    if not form.is_valid():
        messages.error(request, "Comando de cancelamento inválido.")
        return _back_to_order(payment.order_id)

    try:
        services.request_hosted_checkout_cancellation(
            organization=organization,
            intent=payment,
            actor=request.user,
            **form.cleaned_data,
        )
    except PaymentDomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Cancelamento do checkout solicitado a partir do pedido.")
    return _back_to_order(payment.order_id)
