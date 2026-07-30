from django.contrib import admin

from apps.orders.models import Order, OrderCommandReceipt, OrderItem, OrderNumberSequence, OrderStatusHistory


class ReadOnlyDomainAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(ReadOnlyDomainAdmin):
    list_display = ("display_number", "organization", "status", "total", "created_at")
    list_filter = ("organization", "status")
    search_fields = ("number", "customer__display_name")


@admin.register(OrderItem)
class OrderItemAdmin(ReadOnlyDomainAdmin):
    list_display = ("order", "position", "name_snapshot", "quantity", "total")
    list_filter = ("organization",)


admin.site.register(OrderStatusHistory, ReadOnlyDomainAdmin)
admin.site.register(OrderNumberSequence, ReadOnlyDomainAdmin)
admin.site.register(OrderCommandReceipt, ReadOnlyDomainAdmin)
