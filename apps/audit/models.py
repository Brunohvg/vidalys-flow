from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class AuditEvent(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    action = models.CharField(max_length=120, db_index=True)
    entity_type = models.CharField(max_length=120)
    entity_id = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("organization", "entity_type", "entity_id"),
                name="audit_org_entity_idx",
            )
        ]

    def __str__(self):
        return f"{self.action}: {self.entity_type}/{self.entity_id}"

    def delete(self, *args, **kwargs):
        raise TypeError("AuditEvent é imutável.")
