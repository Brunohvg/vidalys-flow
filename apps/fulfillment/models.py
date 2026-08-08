from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class ImmutableFulfillmentQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Fulfillment não pode ser excluído.")


class Fulfillment(BaseModel):
    objects = ImmutableFulfillmentQuerySet.as_manager()

    class Method(models.TextChoices):
        DELIVERY = "delivery", "Entrega"
        PICKUP = "pickup", "Retirada"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        PREPARING = "preparing", "Em separação"
        READY = "ready", "Pronto"
        IN_TRANSIT = "in_transit", "Em trânsito"
        COMPLETED = "completed", "Concluído"
        CANCELLED = "cancelled", "Cancelado"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="fulfillments",
    )
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="fulfillments")
    sequence = models.PositiveIntegerField()
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    destination_snapshot = models.JSONField(default=dict, blank=True)
    snapshot_schema_version = models.PositiveSmallIntegerField(default=1)
    pickup_unit = models.ForeignKey(
        "organizations.OrganizationUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fulfillments",
    )
    pickup_unit_name_snapshot = models.CharField(max_length=200, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fulfillments_created",
    )
    preparing_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=500, blank=True)
    system_cancelled = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("order", "sequence"), name="fulfillment_sequence_unique"),
            models.CheckConstraint(condition=models.Q(sequence__gte=1), name="fulfillment_sequence_positive"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="fulfillment_version_positive"),
            models.CheckConstraint(
                condition=models.Q(method__in=("delivery", "pickup")),
                name="fulfillment_method_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("draft", "preparing", "ready", "in_transit", "completed", "cancelled")
                ),
                name="fulfillment_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(method="delivery", pickup_unit__isnull=True, pickup_unit_name_snapshot="")
                    | models.Q(
                        method="pickup",
                        pickup_unit__isnull=False,
                        destination_snapshot={},
                    )
                    & ~models.Q(pickup_unit_name_snapshot="")
                ),
                name="fulfillment_method_snapshot_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="cancelled", cancelled_at__isnull=True)
                    & ~models.Q(status="cancelled", cancel_reason="")
                    | ~models.Q(status="cancelled")
                    & models.Q(cancelled_at__isnull=True, cancel_reason="", system_cancelled=False)
                ),
                name="fulfillment_cancel_metadata",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status", "created_at"), name="fulfillment_org_status_idx"),
            models.Index(fields=("organization", "order"), name="fulfillment_org_order_idx"),
        ]

    @property
    def display_number(self):
        return f"{self.order.display_number}-F{self.sequence:02d}"

    def __str__(self):
        return self.display_number

    def delete(self, *args, **kwargs):
        raise TypeError("Fulfillment não pode ser excluído.")


class FulfillmentItem(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="fulfillment_items",
    )
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.PROTECT, related_name="items")
    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.PROTECT, related_name="fulfillment_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ("order_item__position",)
        constraints = [
            models.UniqueConstraint(
                fields=("fulfillment", "order_item"),
                name="fulfillment_item_unique",
            ),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="fulfillment_item_quantity_positive"),
        ]
        indexes = [
            models.Index(fields=("organization", "order_item"), name="fulfillment_item_org_order_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("FulfillmentItem não pode ser excluído diretamente.")


class ImmutableHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("FulfillmentStatusHistory é imutável.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("FulfillmentStatusHistory é imutável.")

    def delete(self):
        raise TypeError("FulfillmentStatusHistory é imutável.")


class FulfillmentStatusHistory(BaseModel):
    objects = ImmutableHistoryQuerySet.as_manager()

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="fulfillment_status_history",
    )
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=Fulfillment.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fulfillment_status_changes",
    )
    command_id = models.CharField(max_length=64)
    reason_provided = models.BooleanField(default=False)
    system_generated = models.BooleanField(default=False)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("fulfillment", "to_status"),
                name="fulfillment_history_status_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    from_status__in=("", "draft", "preparing", "ready", "in_transit", "completed", "cancelled")
                ),
                name="fulfillment_history_from_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    to_status__in=("draft", "preparing", "ready", "in_transit", "completed", "cancelled")
                ),
                name="fulfillment_history_to_valid",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("FulfillmentStatusHistory é imutável.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("FulfillmentStatusHistory é imutável.")
        return super().save(*args, **kwargs)


class FulfillmentCommandReceipt(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="fulfillment_command_receipts",
    )
    operation = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fulfillment_command_receipts",
    )
    fulfillment = models.ForeignKey(
        Fulfillment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    source_event_id = models.UUIDField(null=True, blank=True)
    resulting_version = models.PositiveBigIntegerField(null=True, blank=True)
    completed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "operation", "idempotency_key"),
                name="fulfillment_command_idempotency_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "fulfillment"), name="fulfillment_receipt_org_idx"),
        ]
