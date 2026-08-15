from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class OrderNumberSequence(BaseModel):
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="order_number_sequence",
    )
    next_number = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(next_number__gte=1), name="order_sequence_positive"),
        ]


class Order(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        CONFIRMED = "confirmed", "Confirmado"
        CANCELLED = "cancelled", "Cancelado"

    class PricingMode(models.TextChoices):
        ITEMIZED = "itemized", "Por itens"
        MANUAL = "manual", "Valor manual"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="orders")
    number = models.PositiveBigIntegerField()
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    channel = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=3, default="BRL")
    pricing_mode = models.CharField(max_length=20, choices=PricingMode.choices, default=PricingMode.ITEMIZED)
    manual_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    surcharge_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    customer_name_snapshot = models.CharField(max_length=200, blank=True)
    customer_document_snapshot = models.CharField(max_length=14, blank=True)
    customer_contact_snapshot = models.JSONField(default=dict, blank=True)
    shipping_address_snapshot = models.JSONField(default=dict, blank=True)
    billing_address_snapshot = models.JSONField(default=dict, blank=True)
    snapshot_schema_version = models.PositiveSmallIntegerField(default=1)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_created",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("organization", "number"), name="order_number_unique_per_org"),
            models.CheckConstraint(
                condition=models.Q(status__in=("draft", "confirmed", "cancelled")),
                name="order_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(pricing_mode__in=("itemized", "manual")),
                name="order_pricing_mode_valid",
            ),
            models.CheckConstraint(condition=models.Q(currency="BRL"), name="order_currency_brl"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="order_version_positive"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0), name="order_subtotal_non_negative"),
            models.CheckConstraint(condition=models.Q(discount_total__gte=0), name="order_discount_non_negative"),
            models.CheckConstraint(condition=models.Q(surcharge_total__gte=0), name="order_surcharge_non_negative"),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="order_total_non_negative"),
            models.CheckConstraint(
                condition=models.Q(manual_total__isnull=True) | models.Q(manual_total__gte=0),
                name="order_manual_total_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(pricing_mode="itemized", manual_total__isnull=True)
                    | models.Q(
                        pricing_mode="manual",
                        manual_total__isnull=False,
                        subtotal=models.F("manual_total"),
                        total=models.F("manual_total"),
                        discount_total=0,
                        surcharge_total=0,
                    )
                ),
                name="order_pricing_source_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_total__lte=models.F("subtotal")),
                name="order_discount_not_above_subtotal",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total=models.F("subtotal") - models.F("discount_total") + models.F("surcharge_total")
                ),
                name="order_total_formula",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="draft", confirmed_at__isnull=True, cancelled_at__isnull=True, cancel_reason="")
                    | models.Q(
                        status="confirmed",
                        confirmed_at__isnull=False,
                        cancelled_at__isnull=True,
                        cancel_reason="",
                    )
                    | models.Q(status="cancelled", cancelled_at__isnull=False)
                    & ~models.Q(cancel_reason="")
                ),
                name="order_status_metadata_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status", "created_at"), name="order_org_status_created_idx"),
            models.Index(fields=("organization", "customer", "created_at"), name="order_org_customer_idx"),
        ]

    @property
    def display_number(self):
        return f"PED-{self.number:06d}"

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    def __str__(self):
        return self.display_number

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise TypeError("Pedido confirmado ou cancelado não pode ser excluído.")
        return super().delete(*args, **kwargs)


class OrderItem(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField()
    product = models.ForeignKey(
        "products.Product",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    variant = models.ForeignKey(
        "products.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    name_snapshot = models.CharField(max_length=200)
    variant_snapshot = models.CharField(max_length=200, blank=True)
    sku_snapshot = models.CharField(max_length=64, blank=True)
    unit_snapshot = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    gross_total = models.DecimalField(max_digits=14, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    surcharge_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    surcharge_reason = models.CharField(max_length=500, blank=True)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("position",)
        constraints = [
            models.UniqueConstraint(fields=("order", "position"), name="order_item_position_unique"),
            models.CheckConstraint(condition=models.Q(position__gte=1), name="order_item_position_positive"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="order_item_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="order_item_price_non_negative"),
            models.CheckConstraint(condition=models.Q(gross_total__gte=0), name="order_item_gross_non_negative"),
            models.CheckConstraint(condition=models.Q(discount_amount__gte=0), name="order_item_discount_non_negative"),
            models.CheckConstraint(
                condition=models.Q(surcharge_amount__gte=0),
                name="order_item_surcharge_non_negative",
            ),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="order_item_total_non_negative"),
            models.CheckConstraint(
                condition=models.Q(discount_amount__lte=models.F("gross_total")),
                name="order_item_discount_not_above_gross",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total=models.F("gross_total") - models.F("discount_amount") + models.F("surcharge_amount")
                ),
                name="order_item_total_formula",
            ),
            models.CheckConstraint(
                condition=models.Q(variant__isnull=True) | models.Q(product__isnull=False),
                name="order_item_variant_requires_product",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(surcharge_amount=0, surcharge_reason="")
                    | models.Q(surcharge_amount__gt=0) & ~models.Q(surcharge_reason="")
                ),
                name="order_item_surcharge_requires_reason",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "order"), name="order_item_org_order_idx"),
        ]


class ImmutableHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("OrderStatusHistory é imutável.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("OrderStatusHistory é imutável.")

    def delete(self):
        raise TypeError("OrderStatusHistory é imutável.")


class OrderStatusHistory(BaseModel):
    objects = ImmutableHistoryQuerySet.as_manager()

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="order_status_history",
    )
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=Order.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_status_changes",
    )
    command_id = models.CharField(max_length=64)
    reason_provided = models.BooleanField(default=False)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("order", "to_status"), name="order_history_status_unique"),
            models.CheckConstraint(
                condition=models.Q(from_status__in=("", "draft", "confirmed", "cancelled")),
                name="order_history_from_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(to_status__in=("draft", "confirmed", "cancelled")),
                name="order_history_to_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "order", "created_at"), name="order_history_org_order_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("OrderStatusHistory é imutável.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("OrderStatusHistory é imutável.")
        return super().save(*args, **kwargs)


class OrderCommandReceipt(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="order_command_receipts",
    )
    operation = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_command_receipts",
    )
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    result_item_id = models.UUIDField(null=True, blank=True)
    resulting_version = models.PositiveBigIntegerField(null=True, blank=True)
    completed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "operation", "idempotency_key"),
                name="order_command_idempotency_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "order"), name="order_receipt_org_order_idx"),
        ]
