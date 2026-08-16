from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.organizations.selectors import active_organization_for_user
from apps.products import policies, selectors
from apps.products.models import Product, ProductVariant

AUTOCOMPLETE_LIMIT = 10


@login_required
@require_GET
def product_autocomplete(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    can_view = bool(
        organization
        and membership
        and policies.can_view_products(
            user=request.user,
            organization=organization,
        )
    )
    if not can_view:
        return JsonResponse({"results": []}, status=403)

    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    variants = list(
        ProductVariant.objects.filter(
            organization=organization,
            status=Product.Status.ACTIVE,
            product__status=Product.Status.ACTIVE,
        )
        .filter(
            Q(name__icontains=query)
            | Q(sku__icontains=query)
            | Q(barcode__icontains=query)
            | Q(identifiers__value__icontains=query)
        )
        .select_related("product")
        .distinct()
        .order_by("product__name", "name", "sku")[:AUTOCOMPLETE_LIMIT]
    )
    results = [
        {
            "id": f"variant:{variant.id}",
            "product_id": str(variant.product_id),
            "variant_id": str(variant.id),
            "label": " · ".join(
                part
                for part in (
                    variant.product.name,
                    variant.name,
                    variant.sku,
                    variant.barcode,
                )
                if part
            ),
            "unit": variant.product.default_unit,
            "kind": "variant",
        }
        for variant in variants
    ]
    remaining = AUTOCOMPLETE_LIMIT - len(results)
    if remaining:
        products = (
            selectors.search_products(
                organization=organization,
                query=query,
            )
            .only("id", "name", "default_unit")
            .order_by("name")[:remaining]
        )
        results.extend(
            {
                "id": f"product:{product.id}",
                "product_id": str(product.id),
                "variant_id": None,
                "label": product.name,
                "unit": product.default_unit,
                "kind": "product",
            }
            for product in products
        )
    return JsonResponse({"results": results})
