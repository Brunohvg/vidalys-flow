from django.contrib import admin

from apps.customers.models import ContactPoint, Customer, CustomerAddress, CustomerMerge, CustomerNote


class ContactInline(admin.TabularInline):
    model = ContactPoint
    extra = 0
    readonly_fields = (
        "id",
        "kind",
        "value",
        "normalized_value",
        "is_primary",
        "is_verified",
        "is_active",
        "created_at",
        "updated_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj):
        return False


class AddressInline(admin.TabularInline):
    model = CustomerAddress
    extra = 0
    readonly_fields = (
        "id",
        "label",
        "recipient_name",
        "postal_code",
        "street",
        "number",
        "complement",
        "district",
        "city",
        "state",
        "country",
        "reference",
        "is_default_shipping",
        "is_default_billing",
        "is_active",
        "created_at",
        "updated_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj):
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "organization", "customer_type", "status", "created_at")
    list_filter = ("organization", "customer_type", "status")
    search_fields = ("display_name", "legal_name")
    readonly_fields = (
        "id",
        "organization",
        "customer_type",
        "display_name",
        "legal_name",
        "document_normalized",
        "status",
        "notes_summary",
        "merged_into",
        "created_at",
        "updated_at",
    )
    inlines = (ContactInline, AddressInline)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    list_display = ("customer", "organization", "author", "is_active", "created_at")
    list_filter = ("organization", "is_active")
    search_fields = ("customer__display_name",)
    readonly_fields = (
        "id",
        "organization",
        "customer",
        "author",
        "is_active",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CustomerMerge)
class CustomerMergeAdmin(admin.ModelAdmin):
    list_display = ("organization", "source_customer", "target_customer", "performed_by", "created_at")
    list_filter = ("organization",)
    readonly_fields = (
        "id",
        "organization",
        "source_customer",
        "target_customer",
        "performed_by",
        "reason",
        "rules_applied",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
