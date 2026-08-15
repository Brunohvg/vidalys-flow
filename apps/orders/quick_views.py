from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.orders.exceptions import OrderDomainError
from apps.orders.quick_forms import QuickOrderCreateForm
from apps.orders.quick_services import create_quick_order
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
            order = create_quick_order(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except (OrderDomainError, ValueError) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"{order.display_number} criado.")
            return redirect("orders:detail", order_id=order.id)

    return render(
        request,
        "orders/quick_form.html",
        {"organization": organization, "form": form},
    )
