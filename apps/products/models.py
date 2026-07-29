from django.db import models
from django.db.models.functions import Lower

from apps.core.models import BaseModel


class Product(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"
        ARCHIVED = "archived", "Arquivado"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    default_unit = models.CharField(max_length=20, default="un")

    class Meta:
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive", "archived")),
                name="product_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status", "name"), name="product_org_status_name_idx"),
        ]

    def __str__(self):
        return self.name


class ProductVariant(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="product_variants",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    name = models.CharField(max_length=200, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    barcode = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=Product.Status.choices, default=Product.Status.ACTIVE)

    class Meta:
        ordering = ("name", "sku")
        constraints = [
            models.UniqueConstraint(
                "organization",
                Lower("sku"),
                condition=models.Q(sku__gt=""),
                name="product_variant_sku_unique_org",
            ),
            models.UniqueConstraint(
                fields=("organization", "barcode"),
                condition=models.Q(barcode__gt=""),
                name="product_variant_barcode_unique_org",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "inactive", "archived")),
                name="product_variant_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "sku"), name="product_variant_sku_idx"),
            models.Index(fields=("organization", "barcode"), name="product_variant_barcode_idx"),
        ]

    def __str__(self):
        return self.name or self.sku or str(self.id)


class ProductIdentifier(BaseModel):
    class Kind(models.TextChoices):
        SKU = "sku", "SKU alternativo"
        EAN = "ean", "EAN"
        GTIN = "gtin", "GTIN"
        INTERNAL_CODE = "internal_code", "Código interno"
        SUPPLIER_CODE = "supplier_code", "Código de fornecedor"
        OTHER = "other", "Outro"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="product_identifiers",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="identifiers")
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="identifiers",
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    value = models.CharField(max_length=200)

    class Meta:
        ordering = ("kind", "value")
        constraints = [
            models.UniqueConstraint(
                "organization",
                "kind",
                Lower("value"),
                name="product_identifier_unique_org",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=("sku", "ean", "gtin", "internal_code", "supplier_code", "other")),
                name="product_identifier_kind_valid",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.value}"
