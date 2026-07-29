from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Customer(BaseModel):
    class Type(models.TextChoices):
        INDIVIDUAL = "individual", "Pessoa física"
        COMPANY = "company", "Pessoa jurídica"

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"
        BLOCKED = "blocked", "Bloqueado"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customers",
    )
    customer_type = models.CharField(max_length=20, choices=Type.choices)
    display_name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    document_normalized = models.CharField(max_length=14, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes_summary = models.CharField(max_length=500, blank=True)
    merged_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merge_sources",
    )

    class Meta:
        ordering = ("display_name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "document_normalized"),
                condition=models.Q(document_normalized__gt=""),
                name="customer_document_unique_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(customer_type__in=("individual", "company")),
                name="customer_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive", "blocked")),
                name="customer_status_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(id=models.F("merged_into_id")),
                name="customer_cannot_merge_into_self",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status", "display_name"), name="customer_org_status_name_idx"),
        ]

    def __str__(self):
        return self.display_name

    @property
    def is_merged(self):
        return self.merged_into_id is not None


class ContactPoint(BaseModel):
    class Kind(models.TextChoices):
        PHONE = "phone", "Telefone"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="contacts")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    value = models.CharField(max_length=200)
    normalized_value = models.CharField(max_length=200)
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("kind", "-is_primary", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("customer", "kind"),
                condition=models.Q(is_primary=True, is_active=True),
                name="customer_contact_one_active_primary",
            ),
            models.UniqueConstraint(
                fields=("customer", "kind", "normalized_value"),
                condition=models.Q(is_active=True),
                name="customer_contact_active_value_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("customer", "kind", "normalized_value"), name="customer_contact_lookup_idx"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.value}"


class CustomerAddress(BaseModel):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="addresses")
    label = models.CharField(max_length=60, blank=True)
    recipient_name = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    street = models.CharField(max_length=200)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=60)
    country = models.CharField(max_length=2, default="BR")
    reference = models.CharField(max_length=200, blank=True)
    is_default_shipping = models.BooleanField(default=False)
    is_default_billing = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-is_default_shipping", "label", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("customer",),
                condition=models.Q(is_default_shipping=True, is_active=True),
                name="customer_address_one_shipping_default",
            ),
            models.UniqueConstraint(
                fields=("customer",),
                condition=models.Q(is_default_billing=True, is_active=True),
                name="customer_address_one_billing_default",
            ),
        ]

    def __str__(self):
        return f"{self.street}, {self.number} — {self.city}"


class CustomerNote(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customer_notes",
    )
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_notes")
    content = models.CharField(max_length=1000)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Nota {self.id}"


class CustomerMerge(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customer_merges",
    )
    source_customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="merges_as_source")
    target_customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="merges_as_target")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_merges_performed",
    )
    reason = models.CharField(max_length=500)
    rules_applied = models.JSONField(default=dict)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("source_customer",), name="customer_merge_source_once"),
            models.CheckConstraint(
                condition=~models.Q(source_customer=models.F("target_customer")),
                name="customer_merge_distinct_customers",
            ),
        ]

    def __str__(self):
        return f"{self.source_customer_id} → {self.target_customer_id}"

    def delete(self, *args, **kwargs):
        raise TypeError("CustomerMerge é imutável.")
