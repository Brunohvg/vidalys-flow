from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.customers import policies, selectors
from apps.organizations.selectors import active_organization_for_user

AUTOCOMPLETE_LIMIT = 10


@login_required
@require_GET
def customer_autocomplete(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if not organization or not membership or not policies.can_view_customers(user=request.user, organization=organization):
        return JsonResponse({"results": []}, status=403)

    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    customers = selectors.search_customers(
        organization=organization,
        query=query,
    ).only("id", "display_name")[:AUTOCOMPLETE_LIMIT]
    return JsonResponse(
        {
            "results": [
                {"id": str(customer.id), "label": customer.display_name}
                for customer in customers
            ]
        }
    )
