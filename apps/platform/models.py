from django.db import models

from apps.core.models import BaseModel


class OutboxEvent(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Processando"
        RETRY = "retry", "Nova tentativa"
        PROCESSED = "processed", "Processado"
        DEAD = "dead", "Morto"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="outbox_events",
    )
    event_type = models.CharField(max_length=160, db_index=True)
    aggregate_type = models.CharField(max_length=120)
    aggregate_id = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    idempotency_key = models.CharField(max_length=200)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "idempotency_key"),
                name="outbox_idempotency_unique_per_organization",
            )
        ]
        indexes = [
            models.Index(fields=("status", "available_at"), name="outbox_pending_idx"),
        ]

    def __str__(self):
        return f"{self.event_type}: {self.aggregate_type}/{self.aggregate_id}"
