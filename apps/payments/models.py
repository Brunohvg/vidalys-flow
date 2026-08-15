from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class ImmutablePaymentQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Registros financeiros não podem ser excluídos.")


IMMUTABLE_INTENT_UPDATE_FIELDS = frozenset(
    {
        "organization",
        "organization_id",
        "order",
        "order_id",
        "currency",
        "amount",
        "order_number_snapshot",
        "customer_name_snapshot",
        "snapshot_schema_version",
        "created_by",
        "created_by_id",
    }
)
IMMUTABLE_INTENT_FIELDS = frozenset(
    {
        "organization_id",
        "order_id",
        "currency",
        "amount",
        "order_number_snapshot",
        "customer_name_snapshot",
        "snapshot_schema_version",
        "created_by_id",
    }
)


class PaymentIntentQuerySet(ImmutablePaymentQuerySet):
    def update(self, **kwargs):
        if IMMUTABLE_INTENT_UPDATE_FIELDS.intersection(kwargs):
            raise TypeError("Snapshots do PaymentIntent são imutáveis.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if IMMUTABLE_INTENT_UPDATE_FIELDS.intersection(fields):
            raise TypeError("Snapshots do PaymentIntent são imutáveis.")
        return super().bulk_update(objs, fields, batch_size=batch_size)


class PaymentProviderAccount(BaseModel):
    class Provider(models.TextChoices):
        MERCADO_PAGO = "mercado_pago", "Mercado Pago"
        PAGARME = "pagarme", "Pagar.me"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_provider_accounts",
    )
    provider = models.CharField(max_length=30, choices=Provider.choices)
    display_name = models.CharField(max_length=120)
    credential_alias = models.CharField(max_length=120)
    is_active = models.BooleanField(default=False)
    callbacks_enabled = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("provider", "display_name")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "provider", "display_name"),
                name="payment_account_org_provider_name_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(provider__in=("mercado_pago", "pagarme")),
                name="payment_account_provider_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="payment_account_version_positive"),
            models.CheckConstraint(
                condition=models.Q(provider="mercado_pago") | models.Q(callbacks_enabled=False),
                name="payment_pagarme_callback_disabled",
            ),
        ]

    def __str__(self):
        return f"{self.organization} / {self.display_name}"

    def delete(self, *args, **kwargs):
        raise TypeError("PaymentProviderAccount deve ser desativado, não excluído.")


class PaymentIntent(BaseModel):
    objects = PaymentIntentQuerySet.as_manager()

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        AWAITING_PAYMENT = "awaiting_payment", "Aguardando pagamento"
        PROCESSING = "processing", "Processando"
        PAID = "paid", "Pago"
        CANCELLED = "cancelled", "Cancelado"
        EXPIRED = "expired", "Expirado"
        REQUIRES_ATTENTION = "requires_attention", "Requer atenção"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_intents",
    )
    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="payment_intent")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    currency = models.CharField(max_length=3, default="BRL")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    order_number_snapshot = models.CharField(max_length=20)
    customer_name_snapshot = models.CharField(max_length=200)
    snapshot_schema_version = models.PositiveSmallIntegerField(default=1)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_intents_created",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    attention_code = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "pending",
                        "awaiting_payment",
                        "processing",
                        "paid",
                        "cancelled",
                        "expired",
                        "requires_attention",
                    )
                ),
                name="payment_intent_status_valid",
            ),
            models.CheckConstraint(condition=models.Q(currency="BRL"), name="payment_intent_currency_brl"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_intent_amount_positive"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="payment_intent_version_positive"),
            models.CheckConstraint(
                condition=(models.Q(status="paid", paid_at__isnull=False) | ~models.Q(status="paid")),
                name="payment_intent_paid_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="requires_attention") & ~models.Q(attention_code="")
                    | ~models.Q(status="requires_attention") & models.Q(attention_code="")
                ),
                name="payment_intent_attention_code",
            ),
            models.CheckConstraint(
                condition=models.Q(status="cancelled", cancelled_at__isnull=False) | ~models.Q(status="cancelled"),
                name="payment_intent_cancel_timestamp",
            ),
            models.CheckConstraint(
                condition=models.Q(status="expired", expired_at__isnull=False) | ~models.Q(status="expired"),
                name="payment_intent_expired_timestamp",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status", "created_at"), name="payment_intent_org_status_idx"),
        ]

    def __str__(self):
        return f"{self.order_number_snapshot} / {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values(*IMMUTABLE_INTENT_FIELDS).first()
            if original is None:
                raise TypeError("PaymentIntent persistido não foi encontrado.")
            for field in IMMUTABLE_INTENT_FIELDS:
                if getattr(self, field) != original[field]:
                    raise TypeError("Snapshots do PaymentIntent são imutáveis.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("PaymentIntent não pode ser excluído.")


class PaymentAttempt(BaseModel):
    objects = ImmutablePaymentQuerySet.as_manager()

    class Status(models.TextChoices):
        REQUESTED = "requested", "Solicitado"
        ACTIVE = "active", "Ativo"
        PROCESSING = "processing", "Processando"
        PAID = "paid", "Pago"
        FAILED = "failed", "Falhou"
        CANCELLED = "cancelled", "Cancelado"
        EXPIRED = "expired", "Expirado"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_attempts",
    )
    intent = models.ForeignKey(PaymentIntent, on_delete=models.PROTECT, related_name="attempts")
    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        on_delete=models.PROTECT,
        related_name="payment_attempts",
    )
    provider = models.CharField(max_length=30, choices=PaymentProviderAccount.Provider.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    provider_idempotency_key = models.CharField(max_length=64)
    external_resource_id = models.CharField(max_length=160, blank=True)
    hosted_url = models.URLField(max_length=1000, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    dispatch_lease_token = models.UUIDField(null=True, blank=True, editable=False)
    dispatch_lease_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    dispatch_attempts = models.PositiveIntegerField(default=0, editable=False)
    dispatch_available_at = models.DateTimeField(null=True, blank=True, editable=False)
    dispatch_error_code = models.CharField(max_length=40, blank=True, editable=False)
    cancellation_event_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    cancellation_completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("intent", "provider_idempotency_key"),
                name="payment_attempt_idempotency_unique",
            ),
            models.UniqueConstraint(
                fields=("provider_account", "external_resource_id"),
                condition=~models.Q(external_resource_id=""),
                name="payment_attempt_external_unique",
            ),
            models.UniqueConstraint(
                fields=("intent",),
                condition=models.Q(status__in=("requested", "active", "processing")),
                name="payment_attempt_one_active",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("requested", "active", "processing", "paid", "failed", "cancelled", "expired")
                ),
                name="payment_attempt_status_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="payment_attempt_version_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(dispatch_lease_token__isnull=True, dispatch_lease_expires_at__isnull=True)
                    | models.Q(dispatch_lease_token__isnull=False, dispatch_lease_expires_at__isnull=False)
                ),
                name="payment_attempt_lease_complete",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="requested", external_resource_id="", hosted_url="") | ~models.Q(status="requested")
                ),
                name="payment_attempt_requested_empty",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="active") & ~models.Q(external_resource_id="") & ~models.Q(hosted_url="")
                    | ~models.Q(status="active")
                ),
                name="payment_attempt_active_complete",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "intent"), name="payment_attempt_org_intent_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("PaymentAttempt não pode ser excluído.")


class ImmutableHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Histórico financeiro é imutável.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("Histórico financeiro é imutável.")

    def delete(self):
        raise TypeError("Histórico financeiro é imutável.")


class PaymentStatusHistory(BaseModel):
    objects = ImmutableHistoryQuerySet.as_manager()

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_status_history",
    )
    intent = models.ForeignKey(PaymentIntent, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30, choices=PaymentIntent.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payment_status_changes",
    )
    command_id = models.CharField(max_length=64)
    source = models.CharField(max_length=30)
    reason_code = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("intent", "command_id"), name="payment_history_command_unique"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("PaymentStatusHistory é imutável.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("PaymentStatusHistory é imutável.")


class PaymentCommandReceipt(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_command_receipts",
    )
    operation = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_command_receipts",
    )
    intent = models.ForeignKey(
        PaymentIntent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    attempt = models.ForeignKey(
        PaymentAttempt,
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
                name="payment_command_idempotency_unique",
            ),
        ]


class PaymentWebhookReceipt(BaseModel):
    objects = ImmutableHistoryQuerySet.as_manager()
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_webhook_receipts",
    )
    provider_account = models.ForeignKey(
        PaymentProviderAccount,
        on_delete=models.PROTECT,
        related_name="webhook_receipts",
    )
    provider = models.CharField(max_length=30, choices=PaymentProviderAccount.Provider.choices)
    external_event_id = models.CharField(max_length=160)
    external_resource_id = models.CharField(max_length=160)
    authenticated_request_id_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    canonical_result = models.CharField(max_length=30)
    accepted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider_account", "external_resource_id", "authenticated_request_id_digest"),
                name="payment_webhook_replay_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("PaymentWebhookReceipt é imutável.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("PaymentWebhookReceipt é imutável.")


class PixPaymentInstruction(BaseModel):
    class KeyType(models.TextChoices):
        CPF = "cpf", "CPF"
        CNPJ = "cnpj", "CNPJ"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        RANDOM = "random", "Chave aleatória"

    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="pix_payment_instruction",
    )
    key_type = models.CharField(max_length=20, choices=KeyType.choices)
    key_value = models.CharField(max_length=160)
    beneficiary_name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pix_payment_instructions_updated",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(key_type__in=("cpf", "cnpj", "email", "phone", "random")),
                name="pix_instruction_key_type_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="pix_instruction_version_positive"),
            models.CheckConstraint(condition=~models.Q(key_value=""), name="pix_instruction_key_not_empty"),
            models.CheckConstraint(
                condition=~models.Q(beneficiary_name=""),
                name="pix_instruction_beneficiary_not_empty",
            ),
        ]

    def __str__(self):
        return f"PIX / {self.organization} / {self.get_key_type_display()}"

    def delete(self, *args, **kwargs):
        raise TypeError("A instrução PIX deve ser desativada, não excluída.")
