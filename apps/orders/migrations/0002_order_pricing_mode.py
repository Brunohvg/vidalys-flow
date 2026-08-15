from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="pricing_mode",
            field=models.CharField(
                choices=[("itemized", "Por itens"), ("manual", "Valor manual")],
                default="itemized",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="manual_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("pricing_mode__in", ("itemized", "manual"))),
                name="order_pricing_mode_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("manual_total__isnull", True)) | models.Q(("manual_total__gte", 0)),
                name="order_manual_total_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("manual_total__isnull", True), ("pricing_mode", "itemized"))
                    | models.Q(
                        ("discount_total", 0),
                        ("manual_total__isnull", False),
                        ("pricing_mode", "manual"),
                        ("subtotal", models.F("manual_total")),
                        ("surcharge_total", 0),
                        ("total", models.F("manual_total")),
                    )
                ),
                name="order_pricing_source_consistent",
            ),
        ),
    ]
