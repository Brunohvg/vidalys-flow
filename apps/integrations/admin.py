from django.contrib import admin

from .models import (
    IntegrationConnection,
    IntegrationDelivery,
    IntegrationDeliveryAttempt,
    IntegrationEndpoint,
    IntegrationReconciliationRun,
    IntegrationWebhookReceipt,
)


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = ("key", "organization", "adapter_key", "status", "failure_count", "last_success_at")
    list_filter = ("status", "adapter_key")
    search_fields = ("key", "organization__name")
    readonly_fields = ("failure_count", "last_success_at", "degraded_at", "created_at", "updated_at")


@admin.register(IntegrationEndpoint)
class IntegrationEndpointAdmin(admin.ModelAdmin):
    list_display = ("key", "organization", "connection", "direction", "contract_version", "is_active")
    list_filter = ("direction", "is_active")


@admin.register(IntegrationDelivery)
class IntegrationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("operation_key", "organization", "connection", "status", "source_type", "created_at")
    list_filter = ("status", "source_type")
    search_fields = ("source_id", "idempotency_key")
    readonly_fields = ("payload_digest", "created_at", "updated_at")


@admin.register(IntegrationDeliveryAttempt)
class IntegrationDeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ("delivery", "sequence", "status", "retryable", "result_code", "created_at")
    list_filter = ("status", "retryable")
    readonly_fields = ("lease_token", "external_id", "created_at", "updated_at")


@admin.register(IntegrationWebhookReceipt)
class IntegrationWebhookReceiptAdmin(admin.ModelAdmin):
    list_display = ("external_event_id", "organization", "connection", "contract_version", "disposition", "created_at")
    readonly_fields = ("payload_digest", "created_at", "updated_at")


@admin.register(IntegrationReconciliationRun)
class IntegrationReconciliationRunAdmin(admin.ModelAdmin):
    list_display = ("subject_key", "organization", "connection", "status", "result_code", "created_at")
    list_filter = ("status",)
    readonly_fields = ("created_at", "updated_at")
