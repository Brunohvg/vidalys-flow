from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from apps.organizations.selectors import active_organization_for_user
from apps.payments import policies
from apps.payments.exceptions import PaymentDomainError
from apps.payments.models import PixPaymentInstruction
from apps.payments.pix_forms import PixInstructionForm
from apps.payments.pix_services import configure_pix_instruction


@login_required
def pix_settings(request):
    organization, _membership = active_organization_for_user(user=request.user, session=request.session)
    if organization is None or not policies.can_operate_payments(user=request.user, organization=organization):
        raise Http404

    instruction = PixPaymentInstruction.objects.filter(organization=organization).first()
    form = PixInstructionForm(request.POST or None, instruction=instruction)
    if request.method == "POST" and form.is_valid():
        try:
            instruction = configure_pix_instruction(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except PaymentDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Configuração PIX atualizada.")
            return redirect("payments:pix_settings")

    return render(
        request,
        "payments/pix_settings.html",
        {
            "organization": organization,
            "instruction": instruction,
            "form": form,
        },
    )
