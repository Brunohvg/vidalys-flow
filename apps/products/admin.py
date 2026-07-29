from django.contrib import admin

from apps.products.models import Product, ProductIdentifier, ProductVariant


class VariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    readonly_fields = ("id", "name", "sku", "barcode", "status", "created_at", "updated_at")
    can_delete = False

    def has_add_permission(self, request, obj):
        return False


class IdentifierInline(admin.TabularInline):
    model = ProductIdentifier
    extra = 0
    readonly_fields = ("id", "kind", "value", "variant", "created_at", "updated_at")
    can_delete = False

    def has_add_permission(self, request, obj):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "status", "default_unit", "created_at")
    list_filter = ("organization", "status")
    search_fields = ("name", "variants__sku", "variants__barcode")
    readonly_fields = (
        "id",
        "organization",
        "name",
        "description",
        "status",
        "default_unit",
        "created_at",
        "updated_at",
    )
    inlines = (VariantInline, IdentifierInline)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "organization", "name", "sku", "barcode", "status")
    list_filter = ("organization", "status")
    search_fields = ("product__name", "name", "sku", "barcode")
    readonly_fields = (
        "id",
        "organization",
        "product",
        "name",
        "sku",
        "barcode",
        "status",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductIdentifier)
class ProductIdentifierAdmin(admin.ModelAdmin):
    list_display = ("product", "organization", "kind", "value", "variant")
    list_filter = ("organization", "kind")
    search_fields = ("product__name", "value")
    readonly_fields = (
        "id",
        "organization",
        "product",
        "variant",
        "kind",
        "value",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
