from django.contrib import admin

from apps.payments.models import (
    PaymentAttempt,
    PaymentCommandReceipt,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentStatusHistory,
    PaymentWebhookReceipt,
)


class ReadOnlyPaymentAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentIntent)
class PaymentIntentAdmin(ReadOnlyPaymentAdmin):
    list_display = ("order_number_snapshot", "organization", "amount", "currency", "status", "created_at")
    list_filter = ("organization", "status")
    search_fields = ("order_number_snapshot",)


admin.site.register(PaymentProviderAccount, ReadOnlyPaymentAdmin)
admin.site.register(PaymentAttempt, ReadOnlyPaymentAdmin)
admin.site.register(PaymentStatusHistory, ReadOnlyPaymentAdmin)
admin.site.register(PaymentCommandReceipt, ReadOnlyPaymentAdmin)
admin.site.register(PaymentWebhookReceipt, ReadOnlyPaymentAdmin)
