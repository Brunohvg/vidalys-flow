from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import BaseModel
from apps.users.managers import UserManager


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("e-mail", unique=True)
    first_name = models.CharField("nome", max_length=150, blank=True)
    last_name = models.CharField("sobrenome", max_length=150, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acesso administrativo", default=False)
    date_joined = models.DateTimeField("data de entrada", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ("email",)
        constraints = [
            models.UniqueConstraint(Lower("email"), name="users_email_case_insensitive_unique"),
        ]

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_identity(self.email)

    def save(self, *args, **kwargs):
        self.email = self.__class__.objects.normalize_identity(self.email)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.email
