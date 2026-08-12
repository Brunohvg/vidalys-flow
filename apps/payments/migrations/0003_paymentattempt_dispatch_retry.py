from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_dispatch_lease_and_integrity"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentattempt",
            name="dispatch_available_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="paymentattempt",
            name="dispatch_error_code",
            field=models.CharField(blank=True, editable=False, max_length=40),
        ),
    ]
