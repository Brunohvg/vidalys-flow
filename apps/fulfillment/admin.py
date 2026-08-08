from django.contrib import admin

from apps.fulfillment.models import (
    Fulfillment,
    FulfillmentCommandReceipt,
    FulfillmentItem,
    FulfillmentStatusHistory,
)


class ReadOnlyDomainAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Fulfillment)
class FulfillmentAdmin(ReadOnlyDomainAdmin):
    list_display = ("display_number", "organization", "method", "status", "created_at")
    list_filter = ("organization", "method", "status")
    search_fields = ("order__number", "order__customer_name_snapshot")


admin.site.register(FulfillmentItem, ReadOnlyDomainAdmin)
admin.site.register(FulfillmentStatusHistory, ReadOnlyDomainAdmin)
admin.site.register(FulfillmentCommandReceipt, ReadOnlyDomainAdmin)
