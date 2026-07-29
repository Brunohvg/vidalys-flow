from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.customers import policies, selectors, services
from apps.customers.exceptions import CustomerDomainError
from apps.customers.forms import (
    AddressForm,
    ContactForm,
    CustomerCreateForm,
    CustomerEditForm,
    MergeForm,
    NoteForm,
    StatusForm,
)
from apps.organizations.selectors import active_organization_for_user


def _context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_customers(user=request.user, organization=organization):
        return organization, membership
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return redirect("organizations:list")


def _customer_or_404(*, organization, customer_id, include_merged=False):
    customer = selectors.customer_for_organization(
        organization=organization,
        customer_id=customer_id,
        include_merged=include_merged,
    )
    if not customer:
        raise Http404
    return customer


@login_required
def customer_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    query = request.GET.get("q", "")
    return render(
        request,
        "customers/list.html",
        {
            "organization": organization,
            "customers": selectors.search_customers(organization=organization, query=query),
            "query": query,
        },
    )


@login_required
def customer_create(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = CustomerCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            customer = services.create_customer(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except CustomerDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Cliente criado.")
            return redirect("customers:detail", customer_id=customer.id)
    return render(request, "customers/form.html", {"organization": organization, "form": form, "creating": True})


@login_required
def customer_detail(request, customer_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, membership = context
    customer = _customer_or_404(organization=organization, customer_id=customer_id, include_merged=True)
    if customer.is_merged:
        return redirect("customers:detail", customer_id=customer.merged_into_id)
    return render(
        request,
        "customers/detail.html",
        {
            "organization": organization,
            "customer": customer,
            "detail": selectors.customer_detail(
                organization=organization,
                customer=customer,
                membership=membership,
            ),
            "contact_form": ContactForm(),
            "address_form": AddressForm(),
            "note_form": NoteForm(),
            "status_form": StatusForm(initial={"status": customer.status}),
            "merge_form": MergeForm(),
            "can_merge": policies.can_merge_customers(user=request.user, organization=organization),
        },
    )


@login_required
def customer_edit(request, customer_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    customer = _customer_or_404(organization=organization, customer_id=customer_id)
    initial = {
        "display_name": customer.display_name,
        "legal_name": customer.legal_name,
        "notes_summary": customer.notes_summary,
    }
    form = CustomerEditForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_customer(
                organization=organization,
                customer=customer,
                actor=request.user,
                **form.cleaned_data,
            )
        except CustomerDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Cliente atualizado.")
            return redirect("customers:detail", customer_id=customer.id)
    return render(request, "customers/form.html", {"organization": organization, "customer": customer, "form": form})


def _apply_form(request, form_class, callback):
    form = form_class(request.POST)
    if not form.is_valid():
        messages.error(request, "Revise os campos informados.")
        return None
    try:
        return callback(dict(form.cleaned_data))
    except CustomerDomainError as exc:
        messages.error(request, str(exc))
        return None


def _post_context(request, customer_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context, None, None
    organization, _ = context
    customer = _customer_or_404(organization=organization, customer_id=customer_id)
    return None, organization, customer


@login_required
@require_POST
def customer_add_contact(request, customer_id):
    response, organization, customer = _post_context(request, customer_id)
    if response:
        return response
    _apply_form(
        request,
        ContactForm,
        lambda data: services.add_contact(
            organization=organization, customer=customer, actor=request.user, **data
        ),
    )
    return redirect("customers:detail", customer_id=customer.id)


@login_required
@require_POST
def customer_add_address(request, customer_id):
    response, organization, customer = _post_context(request, customer_id)
    if response:
        return response
    _apply_form(
        request,
        AddressForm,
        lambda data: services.add_address(
            organization=organization, customer=customer, actor=request.user, **data
        ),
    )
    return redirect("customers:detail", customer_id=customer.id)


@login_required
@require_POST
def customer_add_note(request, customer_id):
    response, organization, customer = _post_context(request, customer_id)
    if response:
        return response
    _apply_form(
        request,
        NoteForm,
        lambda data: services.add_note(
            organization=organization, customer=customer, actor=request.user, **data
        ),
    )
    return redirect("customers:detail", customer_id=customer.id)


@login_required
@require_POST
def customer_change_status(request, customer_id):
    response, organization, customer = _post_context(request, customer_id)
    if response:
        return response
    _apply_form(
        request,
        StatusForm,
        lambda data: services.set_customer_status(
            organization=organization, customer=customer, actor=request.user, **data
        ),
    )
    return redirect("customers:detail", customer_id=customer.id)


@login_required
@require_POST
def customer_merge(request, customer_id):
    response, organization, source = _post_context(request, customer_id)
    if response:
        return response

    def merge(data):
        target = _customer_or_404(organization=organization, customer_id=data.pop("target_id"))
        return services.merge_customers(
            organization=organization,
            source=source,
            target=target,
            actor=request.user,
            **data,
        )

    result = _apply_form(request, MergeForm, merge)
    if result:
        messages.success(request, "Clientes mesclados.")
        return redirect("customers:detail", customer_id=result.target_customer_id)
    return redirect("customers:detail", customer_id=source.id)
