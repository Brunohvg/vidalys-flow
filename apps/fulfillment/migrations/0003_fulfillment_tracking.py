from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fulfillment", "0002_fulfillmentstatushistory_fulfillment_history_from_valid_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="fulfillment",
            name="tracking_code",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="fulfillment",
            name="tracking_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddConstraint(
            model_name="fulfillment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("method", "delivery"))
                    | models.Q(("method", "pickup"), ("tracking_code", ""), ("tracking_url", ""))
                ),
                name="fulfillment_tracking_delivery_only",
            ),
        ),
    ]
