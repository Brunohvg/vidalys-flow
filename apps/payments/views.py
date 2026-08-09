from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.orders.selectors import order_for_organization
from apps.organizations.selectors import active_organization_for_user
from apps.payments import policies, selectors, services
from apps.payments.callbacks import enforce_callback_rate_limit, process_mercado_pago_callback
from apps.payments.exceptions import PaymentDomainError, ProviderEffectsDisabled
from apps.payments.forms import CheckoutRequestForm, PaymentFilterForm, PaymentIntentCreateForm
from apps.payments.models import PaymentProviderAccount


def _context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_payments(user=request.user, organization=organization):
        return organization, membership
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return redirect("organizations:list")


def _payment_or_404(*, organization, payment_id):
    payment = selectors.payment_for_organization(organization=organization, payment_id=payment_id)
    if payment is None:
        raise Http404
    return payment


@login_required
def payment_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = PaymentFilterForm(request.GET or None)
    filters = form.cleaned_data if form.is_valid() else {}
    if "q" in filters:
        filters["query"] = filters.pop("q")
    payments = Paginator(selectors.search_payments(organization=organization, **filters), 25).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "payments/list.html",
        {"organization": organization, "payments": payments, "filter_form": form},
    )


@login_required
def payment_create(request, order_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    order = order_for_organization(organization=organization, order_id=order_id)
    if order is None:
        raise Http404
    if not policies.can_operate_payments(user=request.user, organization=organization):
        raise Http404
    form = PaymentIntentCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            payment = services.create_payment_intent(
                organization=organization,
                order=order,
                actor=request.user,
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except PaymentDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Pagamento criado.")
            return redirect("payments:detail", payment_id=payment.id)
    return render(request, "payments/form.html", {"organization": organization, "order": order, "form": form})


@login_required
def payment_detail(request, payment_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, membership = context
    payment = _payment_or_404(organization=organization, payment_id=payment_id)
    return render(
        request,
        "payments/detail.html",
        {
            "organization": organization,
            "payment": payment,
            "detail": selectors.payment_detail(
                organization=organization,
                payment=payment,
                user=request.user,
                membership=membership,
            ),
            "checkout_form": CheckoutRequestForm(
                organization=organization,
                payment=payment,
            ),
            "can_operate": policies.can_operate_payments(user=request.user, organization=organization),
        },
    )


@login_required
@require_POST
def payment_request_checkout(request, payment_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    payment = _payment_or_404(organization=organization, payment_id=payment_id)
    form = CheckoutRequestForm(request.POST, organization=organization, payment=payment)
    if form.is_valid():
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
            messages.success(request, "Solicitação registrada sem chamada externa.")
    else:
        messages.error(request, "Comando de checkout inválido.")
    return redirect("payments:detail", payment_id=payment.id)


@csrf_exempt
@require_POST
def mercado_pago_callback(request, provider_account_id):
    if request.content_type != "application/json":
        return HttpResponse(status=415)
    account = (
        PaymentProviderAccount.objects.select_related("organization")
        .filter(
            id=provider_account_id,
            provider=PaymentProviderAccount.Provider.MERCADO_PAGO,
        )
        .first()
    )
    if account is None:
        raise Http404
    try:
        enforce_callback_rate_limit(
            provider_account_id=account.id,
            remote_address=request.META.get("REMOTE_ADDR", "unknown"),
        )
        process_mercado_pago_callback(
            provider_account=account,
            raw_body=request.body,
            request_id=request.headers.get("X-Request-Id", ""),
            signature_header=request.headers.get("X-Signature", ""),
        )
    except ProviderEffectsDisabled:
        return HttpResponse(status=503)
    except PaymentDomainError:
        return HttpResponse(status=400)
    return HttpResponse(status=202)
