from django.conf import settings
from django.db import models

from apps.core.models import BaseModel

MESSAGE_STATES = (
    "pending",
    "queued",
    "sending",
    "sent",
    "delivered",
    "failed",
    "cancelled",
    "uncertain",
)

ATTEMPT_STATES = (
    "requested",
    "sending",
    "accepted",
    "delivered",
    "failed",
    "cancelled",
    "uncertain",
)

CHANNEL_STATES = (
    "inactive",
    "connecting",
    "pairing_required",
    "active",
    "degraded",
    "disconnected",
    "disabled",
)

ACTIVE_ATTEMPT_STATUSES = ("requested", "sending", "accepted", "uncertain")


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Registros de Messaging imutáveis não podem ser atualizados em lote.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("Registros de Messaging imutáveis não podem ser atualizados em lote.")

    def delete(self):
        raise TypeError("Registros de Messaging imutáveis não podem ser excluídos.")


class MessagingProviderConnection(BaseModel):
    class Provider(models.TextChoices):
        EVOLUTION = "evolution", "Evolution API (linked device)"
        WHATSAPP_CLOUD = "whatsapp_cloud", "WhatsApp Business Platform Cloud API"
        SES = "ses", "Amazon SES"

    class Mode(models.TextChoices):
        LINKED_DEVICE = "linked_device", "Dispositivo vinculado (não oficial)"
        OFFICIAL = "official", "API oficial Meta"
        EMAIL = "email", "E-mail transacional"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="messaging_provider_connections",
    )
    provider = models.CharField(max_length=30, choices=Provider.choices)
    mode = models.CharField(max_length=30, choices=Mode.choices)
    display_name = models.CharField(max_length=120)
    credential_alias = models.CharField(max_length=120)
    webhook_secret_alias = models.CharField(max_length=120, blank=True)
    capability_snapshot = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=False)
    callbacks_enabled = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("provider", "display_name")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "provider", "display_name"),
                name="messaging_connection_org_provider_name_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(provider__in=("evolution", "whatsapp_cloud", "ses")),
                name="messaging_connection_provider_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(mode__in=("linked_device", "official", "email")),
                name="messaging_connection_mode_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(provider="evolution", mode="linked_device")
                    | models.Q(provider="whatsapp_cloud", mode="official")
                    | models.Q(provider="ses", mode="email")
                ),
                name="messaging_connection_provider_mode_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="messaging_connection_version_positive"),
        ]

    def __str__(self):
        return f"{self.organization} / {self.display_name}"

    def delete(self, *args, **kwargs):
        raise TypeError("MessagingProviderConnection deve ser desativado, não excluído.")


class MessagingChannel(BaseModel):
    class Kind(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"

    class State(models.TextChoices):
        INACTIVE = "inactive", "Inativo"
        CONNECTING = "connecting", "Conectando"
        PAIRING_REQUIRED = "pairing_required", "Aguardando pareamento"
        ACTIVE = "active", "Ativo"
        DEGRADED = "degraded", "Degradado"
        DISCONNECTED = "disconnected", "Desconectado"
        DISABLED = "disabled", "Desabilitado"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="messaging_channels",
    )
    connection = models.ForeignKey(
        MessagingProviderConnection,
        on_delete=models.PROTECT,
        related_name="channels",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    display_name = models.CharField(max_length=120)
    external_channel_id = models.CharField(max_length=200, blank=True)
    credential_alias = models.CharField(max_length=120, blank=True)
    capability_snapshot = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=30, choices=State.choices, default=State.INACTIVE)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("kind", "display_name")
        constraints = [
            models.UniqueConstraint(
                fields=("connection", "external_channel_id"),
                condition=~models.Q(external_channel_id=""),
                name="messaging_channel_external_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=("whatsapp", "email")),
                name="messaging_channel_kind_valid",
            ),
            models.CheckConstraint(condition=models.Q(state__in=CHANNEL_STATES), name="messaging_channel_state_valid"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="messaging_channel_version_positive"),
        ]

    def __str__(self):
        return f"{self.connection.display_name} / {self.display_name}"

    def delete(self, *args, **kwargs):
        raise TypeError("MessagingChannel deve ser desabilitado, não excluído.")


class MessageTemplate(BaseModel):
    objects = ImmutableQuerySet.as_manager()

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="message_templates",
    )
    semantic_key = models.CharField(max_length=120)
    name = models.CharField(max_length=200)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    locale = models.CharField(max_length=20, default="pt-BR")
    version = models.PositiveBigIntegerField(default=1)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    parameter_schema = models.JSONField(default=list, blank=True)
    provider_template_reference = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("semantic_key", "version")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "semantic_key", "version"),
                name="messaging_template_semantic_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(channel__in=("whatsapp", "email")),
                name="messaging_template_channel_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="messaging_template_version_positive"),
        ]

    def __str__(self):
        return f"{self.semantic_key} v{self.version} ({self.locale})"

    def save(self, *args, **kwargs):
        if not self._state.adding and Message.objects.filter(template_id=self.id).exists():
            raise TypeError("MessageTemplate já usado é imutável; crie uma nova versão.")
        return super().save(*args, **kwargs)


class MessagingPreference(BaseModel):
    class Decision(models.TextChoices):
        ALLOWED = "allowed", "Permitido"
        SUPPRESSED = "suppressed", "Suprimido"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="messaging_preferences",
    )
    contact_point = models.ForeignKey(
        "customers.ContactPoint",
        on_delete=models.PROTECT,
        related_name="messaging_preferences",
    )
    channel = models.CharField(max_length=20, choices=MessageTemplate.Channel.choices)
    purpose = models.CharField(max_length=80)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    provenance = models.CharField(max_length=120)
    policy_version = models.PositiveBigIntegerField(default=1)
    effective_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-effective_at", "-created_at")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(channel__in=("whatsapp", "email")),
                name="messaging_preference_channel_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(decision__in=("allowed", "suppressed")),
                name="messaging_preference_decision_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(policy_version__gte=1),
                name="messaging_preference_policy_version_positive",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "contact_point", "channel", "purpose"), name="messaging_pref_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("MessagingPreference é imutável; alterações criam novo registro.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("MessagingPreference é imutável.")


class MessageAutomationRule(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="message_automation_rules",
    )
    event_type = models.CharField(max_length=120)
    event_version = models.PositiveBigIntegerField(default=1)
    template = models.ForeignKey(MessageTemplate, on_delete=models.PROTECT, related_name="automation_rules")
    channel = models.ForeignKey(MessagingChannel, on_delete=models.PROTECT, related_name="automation_rules")
    purpose = models.CharField(max_length=80)
    is_enabled = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("event_type", "purpose")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "event_type", "template", "channel"),
                name="messaging_rule_event_template_channel_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(event_version__gte=1),
                name="messaging_rule_event_version_positive",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="messaging_rule_version_positive"),
        ]

    def __str__(self):
        return f"{self.event_type} → {self.template.semantic_key}"


class Message(BaseModel):
    objects = ImmutableQuerySet.as_manager()

    class SourceType(models.TextChoices):
        ORDER = "order", "Pedido"
        FULFILLMENT = "fulfillment", "Fulfillment"
        PAYMENT = "payment", "Pagamento"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        QUEUED = "queued", "Na fila"
        SENDING = "sending", "Enviando"
        SENT = "sent", "Enviado"
        DELIVERED = "delivered", "Entregue"
        FAILED = "failed", "Falhou"
        CANCELLED = "cancelled", "Cancelado"
        UNCERTAIN = "uncertain", "Incerto"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="messages",
    )
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    source_id = models.UUIDField()
    source_version = models.PositiveBigIntegerField()
    source_event_id = models.UUIDField(null=True, blank=True)
    purpose = models.CharField(max_length=80)
    template = models.ForeignKey(MessageTemplate, on_delete=models.PROTECT, related_name="messages")
    template_semantic_key = models.CharField(max_length=120)
    template_version = models.PositiveBigIntegerField()
    channel = models.ForeignKey(MessagingChannel, on_delete=models.PROTECT, related_name="messages")
    channel_kind = models.CharField(max_length=20, choices=MessagingChannel.Kind.choices)
    locale = models.CharField(max_length=20)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="messages")
    customer_display_name = models.CharField(max_length=200)
    contact_point = models.ForeignKey(
        "customers.ContactPoint",
        on_delete=models.PROTECT,
        related_name="messages",
    )
    destination_snapshot = models.CharField(max_length=200)
    permission_evidence_id = models.UUIDField(null=True, blank=True)
    permission_policy_version = models.PositiveBigIntegerField(null=True, blank=True)
    parameter_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    version = models.PositiveBigIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="messages_created",
    )
    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=MESSAGE_STATES),
                name="messaging_message_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(source_type__in=("order", "fulfillment", "payment")),
                name="messaging_message_source_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(channel_kind__in=("whatsapp", "email")),
                name="messaging_message_channel_kind_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="messaging_message_version_positive"),
            models.CheckConstraint(
                condition=models.Q(template_version__gte=1),
                name="messaging_message_template_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(source_version__gte=1),
                name="messaging_message_source_version_positive",
            ),
            models.CheckConstraint(
                condition=(models.Q(status="sent", sent_at__isnull=False) | ~models.Q(status="sent")),
                name="messaging_message_sent_timestamp",
            ),
            models.CheckConstraint(
                condition=(models.Q(status="delivered", delivered_at__isnull=False) | ~models.Q(status="delivered")),
                name="messaging_message_delivered_timestamp",
            ),
            models.CheckConstraint(
                condition=(models.Q(status="failed", failed_at__isnull=False) | ~models.Q(status="failed")),
                name="messaging_message_failed_timestamp",
            ),
            models.CheckConstraint(
                condition=(models.Q(status="cancelled", cancelled_at__isnull=False) | ~models.Q(status="cancelled")),
                name="messaging_message_cancelled_timestamp",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status", "created_at"), name="msg_org_status_idx"),
            models.Index(fields=("organization", "source_type", "source_id"), name="msg_source_idx"),
        ]

    def __str__(self):
        return f"{self.purpose} / {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            immutable_fields = (
                "organization_id",
                "source_type",
                "source_id",
                "source_version",
                "source_event_id",
                "purpose",
                "template_id",
                "template_semantic_key",
                "template_version",
                "channel_id",
                "channel_kind",
                "locale",
                "customer_id",
                "customer_display_name",
                "contact_point_id",
                "destination_snapshot",
                "permission_evidence_id",
                "permission_policy_version",
                "parameter_snapshot",
                "created_by_id",
            )
            persisted = type(self)._base_manager.filter(pk=self.pk).values(*immutable_fields).first()
            if persisted is None or any(getattr(self, field) != persisted[field] for field in immutable_fields):
                raise TypeError("Snapshots e vínculos de Message são imutáveis.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Message não pode ser excluído.")


class MessageDeliveryAttempt(BaseModel):
    objects = ImmutableQuerySet.as_manager()

    class Status(models.TextChoices):
        REQUESTED = "requested", "Solicitado"
        SENDING = "sending", "Enviando"
        ACCEPTED = "accepted", "Aceito"
        DELIVERED = "delivered", "Entregue"
        FAILED = "failed", "Falhou"
        CANCELLED = "cancelled", "Cancelado"
        UNCERTAIN = "uncertain", "Incerto"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="message_delivery_attempts",
    )
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name="attempts")
    channel = models.ForeignKey(MessagingChannel, on_delete=models.PROTECT, related_name="delivery_attempts")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    dispatch_key = models.CharField(max_length=64)
    provider_correlation_tag = models.CharField(max_length=160)
    external_message_id = models.CharField(max_length=200, blank=True)
    dispatch_lease_token = models.UUIDField(null=True, blank=True, editable=False)
    dispatch_lease_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    dispatch_attempts = models.PositiveIntegerField(default=0, editable=False)
    dispatch_available_at = models.DateTimeField(null=True, blank=True, editable=False)
    dispatch_error_code = models.CharField(max_length=40, blank=True, editable=False)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("message", "dispatch_key"), name="messaging_attempt_dispatch_key_unique"),
            models.UniqueConstraint(
                fields=("channel", "external_message_id"),
                condition=~models.Q(external_message_id=""),
                name="messaging_attempt_external_unique",
            ),
            models.UniqueConstraint(
                fields=("message",),
                condition=models.Q(status__in=ACTIVE_ATTEMPT_STATUSES),
                name="messaging_attempt_one_active",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ATTEMPT_STATES),
                name="messaging_attempt_status_valid",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="messaging_attempt_version_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(dispatch_lease_token__isnull=True, dispatch_lease_expires_at__isnull=True)
                    | models.Q(dispatch_lease_token__isnull=False, dispatch_lease_expires_at__isnull=False)
                ),
                name="messaging_attempt_lease_complete",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "message"), name="msg_attempt_org_msg_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise TypeError("MessageDeliveryAttempt não pode ser excluído.")


class MessageStatusHistory(BaseModel):
    objects = ImmutableQuerySet.as_manager()

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="message_status_history",
    )
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=Message.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="message_status_changes",
    )
    command_id = models.CharField(max_length=64)
    source = models.CharField(max_length=30)
    reason_code = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("message", "command_id"), name="messaging_history_command_unique"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("MessageStatusHistory é imutável.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("MessageStatusHistory é imutável.")


class MessageCommandReceipt(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="message_command_receipts",
    )
    operation = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="message_command_receipts",
    )
    message = models.ForeignKey(
        Message,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    attempt = models.ForeignKey(
        MessageDeliveryAttempt,
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
                name="messaging_command_idempotency_unique",
            ),
        ]


class MessageWebhookReceipt(BaseModel):
    objects = ImmutableQuerySet.as_manager()

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="message_webhook_receipts",
    )
    connection = models.ForeignKey(
        MessagingProviderConnection,
        on_delete=models.PROTECT,
        related_name="webhook_receipts",
    )
    channel = models.ForeignKey(MessagingChannel, on_delete=models.PROTECT, related_name="webhook_receipts")
    external_event_id = models.CharField(max_length=200)
    external_message_id = models.CharField(max_length=200)
    authenticated_request_id_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    canonical_result = models.CharField(max_length=30)
    has_inconsistency = models.BooleanField(default=False)
    reason_code = models.CharField(max_length=60, blank=True)
    accepted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("channel", "external_message_id", "authenticated_request_id_digest"),
                name="messaging_webhook_replay_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("MessageWebhookReceipt é imutável.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("MessageWebhookReceipt é imutável.")
