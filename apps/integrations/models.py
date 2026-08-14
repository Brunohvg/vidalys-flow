from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class IntegrationConnection(BaseModel):
    class Status(models.TextChoices):
        INACTIVE = "inactive", "Inactive"
        ACTIVE = "active", "Active"
        DEGRADED = "degraded", "Degraded"
        DISABLED = "disabled", "Disabled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_connections",
    )
    key = models.SlugField(max_length=100)
    adapter_key = models.SlugField(max_length=100, default="reference")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INACTIVE)
    secret_alias = models.CharField(max_length=160, blank=True)
    config = models.JSONField(default=dict, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    degraded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "key"),
                name="integrations_connection_key_org_uniq",
            )
        ]

    def clean(self):
        super().clean()
        if self.adapter_key != "reference":
            raise ValidationError({"adapter_key": "Concrete adapters require separate approval."})
        if self.config not in ({}, None):
            raise ValidationError({"config": "Phase 07 reference configuration must remain empty and non-secret."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class IntegrationEndpoint(BaseModel):
    class Direction(models.TextChoices):
        INGRESS = "ingress", "Ingress"
        EGRESS = "egress", "Egress"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_endpoints",
    )
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.PROTECT,
        related_name="endpoints",
    )
    key = models.SlugField(max_length=100)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    contract_version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("connection", "key", "contract_version"),
                name="integrations_endpoint_version_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        if self.connection_id and self.organization_id != self.connection.organization_id:
            raise ValidationError("Endpoint and connection must belong to the same Organization.")
        if self.config not in ({}, None):
            raise ValidationError({"config": "Phase 07 reference configuration must remain empty and non-secret."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class IntegrationDelivery(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        ACCEPTED = "accepted", "Accepted"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        UNCERTAIN = "uncertain", "Uncertain"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_deliveries",
    )
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    endpoint = models.ForeignKey(
        IntegrationEndpoint,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    source_type = models.CharField(max_length=120)
    source_id = models.CharField(max_length=120)
    source_version = models.PositiveIntegerField()
    contract_version = models.PositiveIntegerField()
    operation_key = models.CharField(max_length=120)
    idempotency_key = models.CharField(max_length=160)
    payload_digest = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "idempotency_key"),
                name="integrations_delivery_idem_org_uniq",
            ),
            models.UniqueConstraint(
                fields=(
                    "endpoint",
                    "source_type",
                    "source_id",
                    "source_version",
                    "operation_key",
                    "contract_version",
                ),
                name="integrations_delivery_source_uniq",
            ),
        ]


class IntegrationDeliveryAttempt(BaseModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        SENDING = "sending", "Sending"
        ACCEPTED = "accepted", "Accepted"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        UNCERTAIN = "uncertain", "Uncertain"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_delivery_attempts",
    )
    delivery = models.ForeignKey(
        IntegrationDelivery,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    sequence = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    lease_token = models.CharField(max_length=64, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=160, blank=True)
    result_code = models.CharField(max_length=80, blank=True)
    retryable = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("delivery", "sequence"),
                name="integrations_attempt_sequence_uniq",
            ),
            models.UniqueConstraint(
                fields=("delivery",),
                condition=Q(status__in=("requested", "sending", "accepted", "uncertain")),
                name="integrations_attempt_one_active",
            ),
        ]


class IntegrationWebhookReceipt(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_webhook_receipts",
    )
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.PROTECT,
        related_name="webhook_receipts",
    )
    endpoint = models.ForeignKey(
        IntegrationEndpoint,
        on_delete=models.PROTECT,
        related_name="webhook_receipts",
    )
    external_event_id = models.CharField(max_length=160)
    contract_version = models.PositiveIntegerField()
    payload_digest = models.CharField(max_length=64)
    disposition = models.CharField(max_length=40)
    occurred_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("connection", "endpoint", "external_event_id"),
                name="integrations_webhook_event_uniq",
            )
        ]


class IntegrationReconciliationRun(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        UNCERTAIN = "uncertain", "Uncertain"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_reconciliations",
    )
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.PROTECT,
        related_name="reconciliations",
    )
    delivery = models.ForeignKey(
        IntegrationDelivery,
        on_delete=models.PROTECT,
        related_name="reconciliations",
        null=True,
        blank=True,
    )
    subject_key = models.CharField(max_length=160)
    cursor = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    result_code = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "connection", "subject_key", "cursor"),
                name="integrations_reconcile_idem_uniq",
            )
        ]
