import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.orders import policies, selectors, services
from apps.orders.exceptions import OrderDomainError
from apps.orders.forms import (
    CancelForm,
    CommandForm,
    CustomerChangeForm,
    ItemCreateForm,
    ItemUpdateForm,
    OrderCreateForm,
    OrderFilterForm,
)
from apps.orders.models import OrderItem
from apps.organizations.selectors import active_organization_for_user


def _context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_orders(user=request.user, organization=organization):
        return organization, membership
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return redirect("organizations:list")


def _order_or_404(*, organization, order_id):
    order = selectors.order_for_organization(organization=organization, order_id=order_id)
    if not order:
        raise Http404
    return order


@login_required
def order_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = OrderFilterForm(request.GET or None)
    filters = form.cleaned_data if form.is_valid() else {}
    if "q" in filters:
        filters["query"] = filters.pop("q")
    query_params = request.GET.copy()
    query_params.pop("page", None)
    orders = Paginator(
        selectors.search_orders(organization=organization, **filters),
        25,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/list.html",
        {
            "organization": organization,
            "orders": orders,
            "filter_form": form,
            "querystring": query_params.urlencode(),
        },
    )


@login_required
def order_create(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = OrderCreateForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            order = services.create_order(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except OrderDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"{order.display_number} criado.")
            return redirect("orders:detail", order_id=order.id)
    return render(request, "orders/form.html", {"organization": organization, "form": form})


def _detail_context(*, request, organization, membership, order):
    can_adjust = policies.can_apply_adjustments(user=request.user, organization=organization)
    command_initial = CommandForm.command_initial(version=order.version)
    items = list(order.items.all())
    return {
        "organization": organization,
        "order": order,
        "detail": selectors.order_detail(
            organization=organization,
            order=order,
            membership=membership,
        ),
        "can_adjust": can_adjust,
        "can_cancel": policies.can_cancel_orders(user=request.user, organization=organization),
        "customer_form": CustomerChangeForm(
            organization=organization,
            initial=CommandForm.command_initial(version=order.version),
        ),
        "item_form": ItemCreateForm(
            organization=organization,
            can_adjust=can_adjust,
            initial=CommandForm.command_initial(version=order.version),
        ),
        "item_forms": [
            {
                "item": item,
                "form": ItemUpdateForm(
                    can_adjust=can_adjust,
                    initial={
                        **CommandForm.command_initial(version=order.version),
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "discount_amount": item.discount_amount,
                        "surcharge_amount": item.surcharge_amount,
                        "surcharge_reason": item.surcharge_reason,
                        "notes": item.notes,
                    },
                ),
                "remove_key": str(uuid.uuid4()),
            }
            for item in items
        ],
        "confirm_form": CommandForm(initial=command_initial),
        "cancel_form": CancelForm(initial=CommandForm.command_initial(version=order.version)),
    }


@login_required
def order_detail(request, order_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, membership = context
    order = _order_or_404(organization=organization, order_id=order_id)
    return render(
        request,
        "orders/detail.html",
        _detail_context(
            request=request,
            organization=organization,
            membership=membership,
            order=order,
        ),
    )


def _post_context(request, order_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context, None, None
    organization, _ = context
    return None, organization, _order_or_404(organization=organization, order_id=order_id)


def _run_command(request, form, callback):
    if not form.is_valid():
        messages.error(request, "Revise os campos informados.")
        return None
    try:
        return callback(dict(form.cleaned_data))
    except OrderDomainError as exc:
        messages.error(request, str(exc))
        return None
    except ValueError as exc:
        messages.error(request, str(exc))
        return None


@login_required
@require_POST
def order_change_customer(request, order_id):
    response, organization, order = _post_context(request, order_id)
    if response:
        return response
    form = CustomerChangeForm(request.POST, organization=organization)
    result = _run_command(
        request,
        form,
        lambda data: services.change_customer(
            organization=organization,
            order=order,
            actor=request.user,
            **data,
        ),
    )
    if result:
        messages.success(request, "Cliente atualizado.")
    return redirect("orders:detail", order_id=order.id)


@login_required
@require_POST
def order_add_item(request, order_id):
    response, organization, order = _post_context(request, order_id)
    if response:
        return response
    form = ItemCreateForm(
        request.POST,
        organization=organization,
        can_adjust=policies.can_apply_adjustments(user=request.user, organization=organization),
    )
    result = _run_command(
        request,
        form,
        lambda data: services.add_item(
            organization=organization,
            order=order,
            actor=request.user,
            **data,
        ),
    )
    if result:
        messages.success(request, "Item adicionado.")
    return redirect("orders:detail", order_id=order.id)


def _item_or_404(*, organization, order, item_id):
    item = OrderItem.objects.filter(organization=organization, order=order, id=item_id).first()
    if not item:
        raise Http404
    return item


@login_required
@require_POST
def order_update_item(request, order_id, item_id):
    response, organization, order = _post_context(request, order_id)
    if response:
        return response
    item = _item_or_404(organization=organization, order=order, item_id=item_id)
    form = ItemUpdateForm(
        request.POST,
        can_adjust=policies.can_apply_adjustments(user=request.user, organization=organization),
    )
    result = _run_command(
        request,
        form,
        lambda data: services.update_item(
            organization=organization,
            item=item,
            actor=request.user,
            **data,
        ),
    )
    if result:
        messages.success(request, "Item atualizado.")
    return redirect("orders:detail", order_id=order.id)


@login_required
@require_POST
def order_remove_item(request, order_id, item_id):
    response, organization, order = _post_context(request, order_id)
    if response:
        return response
    item = _item_or_404(organization=organization, order=order, item_id=item_id)
    form = CommandForm(request.POST)
    result = _run_command(
        request,
        form,
        lambda data: services.remove_item(
            organization=organization,
            item=item,
            actor=request.user,
            **data,
        ),
    )
    if result:
        messages.success(request, "Item removido.")
    return redirect("orders:detail", order_id=order.id)


@login_required
@require_POST
def order_confirm(request, order_id):
    response, organization, order = _post_context(request, order_id)
    if response:
        return response
    result = _run_command(
        request,
        CommandForm(request.POST),
        lambda data: services.confirm_order(
            organization=organization,
            order=order,
            actor=request.user,
            **data,
        ),
    )
    if result:
        messages.success(request, "Pedido confirmado.")
    return redirect("orders:detail", order_id=order.id)


@login_required
@require_POST
def order_cancel(request, order_id):
    response, organization, order = _post_context(request, order_id)
    if response:
        return response
    result = _run_command(
        request,
        CancelForm(request.POST),
        lambda data: services.cancel_order(
            organization=organization,
            order=order,
            actor=request.user,
            **data,
        ),
    )
    if result:
        messages.success(request, "Pedido cancelado.")
    return redirect("orders:detail", order_id=order.id)
