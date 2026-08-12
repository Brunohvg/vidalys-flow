from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_paymentattempt_dispatch_retry"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentattempt",
            name="cancellation_completed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="paymentattempt",
            name="cancellation_event_id",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
    ]
