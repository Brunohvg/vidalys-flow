from django.contrib import admin

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "entity_type", "entity_id", "organization", "created_at")
    readonly_fields = (
        "id",
        "organization",
        "actor",
        "action",
        "entity_type",
        "entity_id",
        "payload",
        "correlation_id",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
