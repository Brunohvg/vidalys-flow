from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import BaseModel


class Organization(BaseModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("slug"), name="organizations_slug_case_insensitive_unique"),
        ]

    def __str__(self):
        return self.name


class OrganizationUnit(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="units")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"),
                name="organization_unit_name_unique_per_organization",
            ),
        ]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class Membership(BaseModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Proprietário"
        ADMIN = "admin", "Administrador"
        MANAGER = "manager", "Gerente"
        OPERATOR = "operator", "Operador"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("organization", "user")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="membership_user_unique_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("owner", "admin", "manager", "operator")),
                name="membership_role_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "is_active", "role"),
                name="membership_org_active_role_idx",
            )
        ]

    def __str__(self):
        return f"{self.organization} / {self.user} / {self.role}"
