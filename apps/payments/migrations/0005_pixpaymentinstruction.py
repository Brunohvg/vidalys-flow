import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0004_paymentattempt_cancellation_correlation"),
        ("organizations", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PixPaymentInstruction",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "key_type",
                    models.CharField(
                        choices=[
                            ("cpf", "CPF"),
                            ("cnpj", "CNPJ"),
                            ("email", "E-mail"),
                            ("phone", "Telefone"),
                            ("random", "Chave aleatória"),
                        ],
                        max_length=20,
                    ),
                ),
                ("key_value", models.CharField(max_length=160)),
                ("beneficiary_name", models.CharField(max_length=200)),
                ("bank_name", models.CharField(blank=True, max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("version", models.PositiveBigIntegerField(default=1)),
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pix_payment_instruction",
                        to="organizations.organization",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pix_payment_instructions_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="pixpaymentinstruction",
            constraint=models.CheckConstraint(
                condition=models.Q(key_type__in=("cpf", "cnpj", "email", "phone", "random")),
                name="pix_instruction_key_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="pixpaymentinstruction",
            constraint=models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="pix_instruction_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="pixpaymentinstruction",
            constraint=models.CheckConstraint(
                condition=~models.Q(key_value=""),
                name="pix_instruction_key_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="pixpaymentinstruction",
            constraint=models.CheckConstraint(
                condition=~models.Q(beneficiary_name=""),
                name="pix_instruction_beneficiary_not_empty",
            ),
        ),
    ]
