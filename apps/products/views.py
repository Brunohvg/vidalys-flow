from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.organizations.selectors import active_organization_for_user
from apps.products import policies, selectors, services
from apps.products.exceptions import ProductDomainError
from apps.products.forms import IdentifierForm, ProductForm, StatusForm, VariantForm


def _context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_products(user=request.user, organization=organization):
        return organization, membership
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return redirect("organizations:list")


def _product_or_404(*, organization, product_id):
    product = selectors.product_for_organization(organization=organization, product_id=product_id)
    if not product:
        raise Http404
    return product


@login_required
def product_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    query = request.GET.get("q", "")
    products = Paginator(
        selectors.search_products(organization=organization, query=query),
        25,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "products/list.html",
        {
            "organization": organization,
            "products": products,
            "query": query,
        },
    )


@login_required
def product_create(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            product = services.create_product(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except ProductDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Produto criado.")
            return redirect("products:detail", product_id=product.id)
    return render(request, "products/form.html", {"organization": organization, "form": form, "creating": True})


@login_required
def product_detail(request, product_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    product = _product_or_404(organization=organization, product_id=product_id)
    return render(
        request,
        "products/detail.html",
        {
            "organization": organization,
            "product": product,
            "variants": product.variants.all(),
            "identifiers": product.identifiers.all(),
            "variant_form": VariantForm(),
            "identifier_form": IdentifierForm(),
            "status_form": StatusForm(initial={"status": product.status}),
        },
    )


@login_required
def product_edit(request, product_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    product = _product_or_404(organization=organization, product_id=product_id)
    initial = {
        "name": product.name,
        "description": product.description,
        "default_unit": product.default_unit,
    }
    form = ProductForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_product(
                organization=organization,
                product=product,
                actor=request.user,
                **form.cleaned_data,
            )
        except ProductDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Produto atualizado.")
            return redirect("products:detail", product_id=product.id)
    return render(request, "products/form.html", {"organization": organization, "product": product, "form": form})


def _post_context(request, product_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context, None, None
    organization, _ = context
    product = _product_or_404(organization=organization, product_id=product_id)
    return None, organization, product


def _apply_form(request, form_class, callback):
    form = form_class(request.POST)
    if not form.is_valid():
        messages.error(request, "Revise os campos informados.")
        return
    try:
        callback(form.cleaned_data)
    except ProductDomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Operação concluída.")


@login_required
@require_POST
def product_add_variant(request, product_id):
    response, organization, product = _post_context(request, product_id)
    if response:
        return response
    _apply_form(
        request,
        VariantForm,
        lambda data: services.create_variant(
            organization=organization,
            product=product,
            actor=request.user,
            **data,
        ),
    )
    return redirect("products:detail", product_id=product.id)


@login_required
@require_POST
def product_add_identifier(request, product_id):
    response, organization, product = _post_context(request, product_id)
    if response:
        return response
    _apply_form(
        request,
        IdentifierForm,
        lambda data: services.add_identifier(
            organization=organization,
            product=product,
            actor=request.user,
            **data,
        ),
    )
    return redirect("products:detail", product_id=product.id)


@login_required
@require_POST
def product_change_status(request, product_id):
    response, organization, product = _post_context(request, product_id)
    if response:
        return response
    _apply_form(
        request,
        StatusForm,
        lambda data: services.set_product_status(
            organization=organization,
            product=product,
            actor=request.user,
            **data,
        ),
    )
    return redirect("products:detail", product_id=product.id)
