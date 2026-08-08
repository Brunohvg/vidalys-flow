from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.fulfillment import policies, selectors, services
from apps.fulfillment.exceptions import FulfillmentDomainError
from apps.fulfillment.forms import (
    CancelForm,
    FulfillmentAllocationForm,
    FulfillmentCreateForm,
    FulfillmentFilterForm,
    TransitionForm,
)
from apps.fulfillment.models import Fulfillment
from apps.orders.selectors import order_for_organization
from apps.organizations.selectors import active_organization_for_user


def _context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_fulfillments(user=request.user, organization=organization):
        return organization, membership
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return redirect("organizations:list")


def _fulfillment_or_404(*, organization, fulfillment_id):
    fulfillment = selectors.fulfillment_for_organization(
        organization=organization,
        fulfillment_id=fulfillment_id,
    )
    if fulfillment is None:
        raise Http404
    return fulfillment


def _order_or_404(*, organization, order_id):
    order = order_for_organization(organization=organization, order_id=order_id)
    if order is None:
        raise Http404
    return order


@login_required
def fulfillment_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = FulfillmentFilterForm(request.GET or None)
    filters = form.cleaned_data if form.is_valid() else {}
    if "q" in filters:
        filters["query"] = filters.pop("q")
    query_params = request.GET.copy()
    query_params.pop("page", None)
    fulfillments = Paginator(
        selectors.search_fulfillments(organization=organization, **filters),
        25,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "fulfillment/list.html",
        {
            "organization": organization,
            "fulfillments": fulfillments,
            "filter_form": form,
            "querystring": query_params.urlencode(),
        },
    )


@login_required
def fulfillment_create(request, order_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    order = _order_or_404(organization=organization, order_id=order_id)
    form = FulfillmentCreateForm(
        request.POST or None,
        organization=organization,
        order=order,
    )
    if request.method == "POST" and form.is_valid():
        try:
            fulfillment = services.create_fulfillment(
                organization=organization,
                order=order,
                actor=request.user,
                method=form.cleaned_data["method"],
                pickup_unit=form.cleaned_data["pickup_unit"],
                allocations=form.cleaned_data["allocations"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except (FulfillmentDomainError, ValueError) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"{fulfillment.display_number} criado.")
            return redirect("fulfillment:detail", fulfillment_id=fulfillment.id)
    return render(
        request,
        "fulfillment/form.html",
        {"organization": organization, "order": order, "form": form},
    )


def _detail_context(*, request, organization, membership, fulfillment):
    initial = TransitionForm.command_initial(version=fulfillment.version)
    item_initial = {item.order_item_id: item.quantity for item in fulfillment.items.all()}
    return {
        "organization": organization,
        "fulfillment": fulfillment,
        "detail": selectors.fulfillment_detail(
            organization=organization,
            fulfillment=fulfillment,
            user=request.user,
            membership=membership,
        ),
        "allocation_form": FulfillmentAllocationForm(
            order=fulfillment.order,
            initial={**initial, **{f"quantity_{key}": value for key, value in item_initial.items()}},
            initial_allocations=item_initial,
        ),
        "transition_form": TransitionForm(initial=initial),
        "cancel_form": CancelForm(initial=initial),
        "can_cancel": policies.can_cancel_fulfillments(user=request.user, organization=organization),
    }


@login_required
def fulfillment_detail(request, fulfillment_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, membership = context
    fulfillment = _fulfillment_or_404(organization=organization, fulfillment_id=fulfillment_id)
    return render(
        request,
        "fulfillment/detail.html",
        _detail_context(
            request=request,
            organization=organization,
            membership=membership,
            fulfillment=fulfillment,
        ),
    )


@login_required
@require_POST
def fulfillment_update(request, fulfillment_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    fulfillment = _fulfillment_or_404(organization=organization, fulfillment_id=fulfillment_id)
    form = FulfillmentAllocationForm(request.POST, order=fulfillment.order)
    if form.is_valid():
        try:
            services.replace_allocations(
                organization=organization,
                fulfillment=fulfillment,
                actor=request.user,
                allocations=form.cleaned_data["allocations"],
                expected_version=form.cleaned_data["expected_version"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except (FulfillmentDomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Quantidades atualizadas.")
    else:
        messages.error(request, "Revise as quantidades informadas.")
    return redirect("fulfillment:detail", fulfillment_id=fulfillment.id)


@login_required
@require_POST
def fulfillment_transition(request, fulfillment_id, target_status):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    fulfillment = _fulfillment_or_404(organization=organization, fulfillment_id=fulfillment_id)
    valid_targets = {choice for choice, _ in Fulfillment.Status.choices} - {
        Fulfillment.Status.DRAFT,
        Fulfillment.Status.CANCELLED,
    }
    if target_status not in valid_targets:
        raise Http404
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
            messages.success(request, "Estado atualizado.")
    else:
        messages.error(request, "Comando inválido.")
    return redirect("fulfillment:detail", fulfillment_id=fulfillment.id)


@login_required
@require_POST
def fulfillment_cancel(request, fulfillment_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    fulfillment = _fulfillment_or_404(organization=organization, fulfillment_id=fulfillment_id)
    form = CancelForm(request.POST)
    if form.is_valid():
        try:
            services.transition_fulfillment(
                organization=organization,
                fulfillment=fulfillment,
                actor=request.user,
                target_status=Fulfillment.Status.CANCELLED,
                **form.cleaned_data,
            )
        except (FulfillmentDomainError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Fulfillment cancelado.")
    else:
        messages.error(request, "Informe o motivo do cancelamento.")
    return redirect("fulfillment:detail", fulfillment_id=fulfillment.id)
