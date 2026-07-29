from django.db.models import Q

from apps.products.models import Product, ProductIdentifier, ProductVariant


def products_for_organization(*, organization, include_inactive=False):
    queryset = Product.objects.filter(organization=organization)
    if not include_inactive:
        queryset = queryset.filter(status=Product.Status.ACTIVE)
    return queryset


def search_products(*, organization, query="", include_inactive=False):
    queryset = products_for_organization(organization=organization, include_inactive=include_inactive)
    query = (query or "").strip()
    if not query:
        return queryset
    return queryset.filter(
        Q(name__icontains=query)
        | Q(variants__sku__icontains=query)
        | Q(variants__barcode__icontains=query)
        | Q(identifiers__value__icontains=query)
    ).distinct()


def product_for_organization(*, organization, product_id):
    return Product.objects.filter(organization=organization, id=product_id).first()


def variant_by_sku(*, organization, sku):
    return ProductVariant.objects.filter(organization=organization, sku__iexact=sku).select_related("product").first()


def identifier_for_organization(*, organization, kind, value):
    return (
        ProductIdentifier.objects.filter(organization=organization, kind=kind, value__iexact=value)
        .select_related("product", "variant")
        .first()
    )
