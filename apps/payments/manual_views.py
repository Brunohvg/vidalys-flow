from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.organizations.selectors import active_organization_for_user
from apps.payments import policies, selectors
from apps.payments.exceptions import PaymentDomainError
from apps.payments.manual_forms import ManualPaymentForm
from apps.payments.manual_services import confirm_manual_payment


@login_required
@require_POST
def payment_confirm_manual(request, payment_id):
    organization, _membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or not policies.can_operate_payments(user=request.user, organization=organization):
        raise Http404

    payment = selectors.payment_for_organization(organization=organization, payment_id=payment_id)
    if payment is None:
        raise Http404

    form = ManualPaymentForm(request.POST, payment=payment)
    if not form.is_valid():
        messages.error(request, "Confirmação manual inválida.")
        return redirect("payments:detail", payment_id=payment.id)

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
        messages.success(request, "Pagamento recebido confirmado manualmente.")
    return redirect("payments:detail", payment_id=payment.id)
