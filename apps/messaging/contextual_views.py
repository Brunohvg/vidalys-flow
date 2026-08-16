import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from apps.customers.models import ContactPoint
from apps.fulfillment.models import Fulfillment
from apps.messaging import contextual, policies
from apps.messaging.exceptions import MessagingDomainError
from apps.messaging.models import MessagingChannel
from apps.organizations.selectors import active_organization_for_user
from apps.payments import policies as payment_policies
from apps.payments.models import PaymentIntent


class ContextualSendForm(forms.Form):
    channel = forms.ModelChoiceField(queryset=MessagingChannel.objects.none(), label="Canal")
    contact_point = forms.ModelChoiceField(queryset=ContactPoint.objects.none(), label="Contato")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["channel"].queryset = MessagingChannel.objects.filter(
            organization=organization,
            state=MessagingChannel.State.ACTIVE,
        ).order_by("kind", "display_name")
        self.fields["contact_point"].queryset = ContactPoint.objects.filter(
            customer=customer,
            is_active=True,
        ).order_by("kind", "created_at")
        if not self.is_bound:
            self.initial["idempotency_key"] = str(uuid.uuid4())


def _context(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if not organization or not membership:
        return None, redirect("organizations:list")
    if not policies.can_view_messages(user=request.user, organization=organization):
        raise Http404
    return organization, None


def _source(*, organization, actor, kind, source_id):
    if kind == "pix":
        if not payment_policies.can_operate_payments(user=actor, organization=organization):
            raise Http404
        source = (
            PaymentIntent.objects.select_related("order__customer")
            .filter(organization=organization, id=source_id)
            .first()
        )
        if source is None:
            raise Http404
        return source, source.order.customer, source.order, "Enviar instruções PIX"
    if kind == "tracking":
        source = (
            Fulfillment.objects.select_related("order__customer")
            .filter(organization=organization, id=source_id)
            .first()
        )
        if source is None:
            raise Http404
        return source, source.order.customer, source.order, "Enviar rastreio"
    raise Http404


@login_required
def contextual_send(request, kind, source_id):
    organization, response = _context(request)
    if response:
        return response
    source, customer, order, title = _source(
        organization=organization,
        actor=request.user,
        kind=kind,
        source_id=source_id,
    )
    form = ContextualSendForm(
        request.POST or None,
        organization=organization,
        customer=customer,
    )
    if request.method == "POST" and form.is_valid():
        try:
            if kind == "pix":
                contextual.create_pix_message(
                    organization=organization,
                    actor=request.user,
                    intent=source,
                    **form.cleaned_data,
                )
            else:
                contextual.create_tracking_message(
                    organization=organization,
                    actor=request.user,
                    fulfillment=source,
                    **form.cleaned_data,
                )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Mensagem transacional registrada sem efeito externo direto.")
            return redirect("orders:detail", order_id=order.id)
    return render(
        request,
        "messaging/contextual_send.html",
        {
            "organization": organization,
            "order": order,
            "title": title,
            "kind": kind,
            "form": form,
        },
    )
