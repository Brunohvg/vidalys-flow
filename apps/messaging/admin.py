from django.contrib import admin

from apps.messaging import policies
from apps.messaging.models import (
    Message,
    MessageAutomationRule,
    MessageCommandReceipt,
    MessageDeliveryAttempt,
    MessageStatusHistory,
    MessageTemplate,
    MessageWebhookReceipt,
    MessagingChannel,
    MessagingPreference,
    MessagingProviderConnection,
)
from apps.organizations.selectors import active_organization_for_user


class ReadOnlyMessagingAdmin(admin.ModelAdmin):
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


@admin.register(Message)
class MessageAdmin(ReadOnlyMessagingAdmin):
    list_display = ("purpose", "customer_display_name", "channel_kind", "status", "created_at")
    list_filter = ("status", "channel_kind")
    search_fields = ("customer_display_name", "template_semantic_key", "purpose")


admin.site.register(MessagingProviderConnection, ReadOnlyMessagingAdmin)
admin.site.register(MessagingChannel, ReadOnlyMessagingAdmin)
admin.site.register(MessageTemplate, ReadOnlyMessagingAdmin)
admin.site.register(MessagingPreference, ReadOnlyMessagingAdmin)
admin.site.register(MessageAutomationRule, ReadOnlyMessagingAdmin)
admin.site.register(MessageDeliveryAttempt, ReadOnlyMessagingAdmin)
admin.site.register(MessageStatusHistory, ReadOnlyMessagingAdmin)
admin.site.register(MessageCommandReceipt, ReadOnlyMessagingAdmin)
admin.site.register(MessageWebhookReceipt, ReadOnlyMessagingAdmin)
