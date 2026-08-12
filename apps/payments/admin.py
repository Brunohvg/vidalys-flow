from django.contrib import admin

from apps.organizations.selectors import active_organization_for_user
from apps.payments import policies
from apps.payments.models import (
    PaymentAttempt,
    PaymentCommandReceipt,
    PaymentIntent,
    PaymentProviderAccount,
    PaymentStatusHistory,
    PaymentWebhookReceipt,
)


class ReadOnlyPaymentAdmin(admin.ModelAdmin):
    def _authorized_organization(self, request):
        organization, _ = active_organization_for_user(
            user=request.user,
            session=getattr(request, "session", {}),
        )
        if organization is None or not policies.can_view_provider_evidence(
            user=request.user,
            organization=organization,
        ):
            return None
        return organization

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        organization = self._authorized_organization(request)
        if organization is None:
            return queryset.none()
        return queryset.filter(organization=organization)

    def has_module_permission(self, request):
        return bool(super().has_module_permission(request) and self._authorized_organization(request))

    def has_view_permission(self, request, obj=None):
        organization = self._authorized_organization(request)
        if organization is None or (obj is not None and obj.organization_id != organization.id):
            return False
        return super().has_view_permission(request, obj)

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
