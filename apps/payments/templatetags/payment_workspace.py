from django import template

from apps.payments import policies, selectors
from apps.payments.forms import CheckoutRequestForm, PaymentCommandForm, PaymentIntentCreateForm
from apps.payments.manual_forms import ManualPaymentForm
from apps.payments.models import PaymentAttempt, PaymentIntent, PixPaymentInstruction
from apps.payments.services import ACTIVE_ATTEMPT_STATUSES

register = template.Library()


@register.inclusion_tag("payments/_order_workspace.html", takes_context=True)
def payment_order_workspace(context, organization, order):
    request = context["request"]
    membership = policies.membership_for(user=request.user, organization=organization)
    if membership is None or order.organization_id != organization.id:
        return {"visible": False}

    can_operate = policies.can_operate_payments(user=request.user, organization=organization)
    payment = PaymentIntent.objects.filter(organization=organization, order=order).first()
    pix = PixPaymentInstruction.objects.filter(organization=organization, is_active=True).first()

    result = {
        "visible": True,
        "request": request,
        "organization": organization,
        "order": order,
        "payment": payment,
        "pix": pix,
        "can_operate": can_operate,
        "create_form": PaymentIntentCreateForm() if can_operate and payment is None else None,
        "manual_form": None,
        "checkout_form": None,
        "cancel_form": None,
        "payment_detail": None,
        "has_checkout_accounts": False,
        "has_active_checkout": False,
    }
    if payment is None:
        return result

    detail = selectors.payment_detail(
        organization=organization,
        payment=payment,
        user=request.user,
        membership=membership,
    )
    result["payment_detail"] = detail

    if can_operate:
        result["manual_form"] = ManualPaymentForm(payment=payment)
        checkout_form = CheckoutRequestForm(organization=organization, payment=payment)
        result["checkout_form"] = checkout_form
        result["has_checkout_accounts"] = checkout_form.fields["provider_account"].queryset.exists()
        result["cancel_form"] = PaymentCommandForm(payment=payment)
        result["has_active_checkout"] = PaymentAttempt.objects.filter(
            organization=organization,
            intent=payment,
            status__in=ACTIVE_ATTEMPT_STATUSES,
        ).exists()
    return result
