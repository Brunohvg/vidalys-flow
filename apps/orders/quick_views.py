from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.customers.exceptions import CustomerDomainError
from apps.fulfillment.exceptions import FulfillmentDomainError
from apps.orders.exceptions import OrderDomainError
from apps.orders.quick_forms import QuickOrderCreateForm
from apps.orders.quick_services import create_quick_sale
from apps.organizations.selectors import active_organization_for_user


@login_required
def order_create(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if not organization or not membership:
        messages.info(request, "Selecione uma organização ativa para continuar.")
        return redirect("organizations:list")

    form = QuickOrderCreateForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            order, fulfillment = create_quick_sale(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except (OrderDomainError, CustomerDomainError, FulfillmentDomainError, ValueError) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                f"{order.display_number} confirmado com atendimento {fulfillment.get_method_display().lower()}.",
            )
            return redirect("orders:detail", order_id=order.id)

    return render(
        request,
        "orders/quick_form.html",
        {"organization": organization, "form": form},
    )
