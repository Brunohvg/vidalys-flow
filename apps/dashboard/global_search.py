from apps.customers.selectors import search_customers
from apps.orders.selectors import search_orders
from apps.products.selectors import search_products

GLOBAL_SEARCH_LIMIT = 6


def global_search_for_organization(*, organization, query, limit=GLOBAL_SEARCH_LIMIT):
    query = (query or "").strip()
    if not query:
        return {"orders": [], "customers": [], "products": []}
    return {
        "orders": list(search_orders(organization=organization, query=query)[:limit]),
        "customers": list(search_customers(organization=organization, query=query)[:limit]),
        "products": list(search_products(organization=organization, query=query)[:limit]),
    }
