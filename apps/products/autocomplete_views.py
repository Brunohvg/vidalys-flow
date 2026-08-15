from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.organizations.selectors import active_organization_for_user
from apps.products import policies, selectors

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

    products = selectors.search_products(
        organization=organization,
        query=query,
    ).only("id", "name", "default_unit")[:AUTOCOMPLETE_LIMIT]
    return JsonResponse(
        {
            "results": [
                {
                    "id": str(product.id),
                    "label": product.name,
                    "unit": product.default_unit,
                }
                for product in products
            ]
        }
    )
