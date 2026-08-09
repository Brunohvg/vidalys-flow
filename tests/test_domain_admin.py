import pytest
from django.contrib import admin

from apps.customers.admin import CustomerMergeAdmin
from apps.customers.models import Customer, CustomerMerge
from apps.payments.models import PaymentAttempt, PaymentIntent, PaymentProviderAccount
from apps.products.admin import ProductAdmin
from apps.products.models import Product, ProductIdentifier, ProductVariant


@pytest.mark.django_db
def test_native_domain_models_are_registered_in_admin():
    assert Customer in admin.site._registry
    assert CustomerMerge in admin.site._registry
    assert Product in admin.site._registry
    assert ProductVariant in admin.site._registry
    assert ProductIdentifier in admin.site._registry
    assert PaymentIntent in admin.site._registry
    assert PaymentAttempt in admin.site._registry
    assert PaymentProviderAccount in admin.site._registry


def test_admin_does_not_bypass_critical_invariants(rf):
    request = rf.get("/admin/")
    merge_admin = CustomerMergeAdmin(CustomerMerge, admin.site)
    product_admin = ProductAdmin(Product, admin.site)
    assert not merge_admin.has_add_permission(request)
    assert not merge_admin.has_delete_permission(request)
    assert not product_admin.has_delete_permission(request)
    assert "status" in product_admin.readonly_fields
