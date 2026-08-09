from django.db import migrations, models


IMMUTABLE_SNAPSHOT_TRIGGER = """
CREATE FUNCTION payments_paymentintent_protect_snapshot() RETURNS trigger AS $$
BEGIN
    IF ROW(
        NEW.organization_id,
        NEW.order_id,
        NEW.currency,
        NEW.amount,
        NEW.order_number_snapshot,
        NEW.customer_name_snapshot,
        NEW.snapshot_schema_version,
        NEW.created_by_id
    ) IS DISTINCT FROM ROW(
        OLD.organization_id,
        OLD.order_id,
        OLD.currency,
        OLD.amount,
        OLD.order_number_snapshot,
        OLD.customer_name_snapshot,
        OLD.snapshot_schema_version,
        OLD.created_by_id
    ) THEN
        RAISE EXCEPTION 'PaymentIntent snapshots are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payments_paymentintent_snapshot_immutable
BEFORE UPDATE ON payments_paymentintent
FOR EACH ROW EXECUTE FUNCTION payments_paymentintent_protect_snapshot();
"""

DROP_IMMUTABLE_SNAPSHOT_TRIGGER = """
DROP TRIGGER IF EXISTS payments_paymentintent_snapshot_immutable ON payments_paymentintent;
DROP FUNCTION IF EXISTS payments_paymentintent_protect_snapshot();
"""


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="paymentattempt",
            name="dispatch_attempts",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="paymentattempt",
            name="dispatch_lease_expires_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="paymentattempt",
            name="dispatch_lease_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="paymentwebhookreceipt",
            name="authenticated_request_id_digest",
            field=models.CharField(default="legacy", max_length=64),
            preserve_default=False,
        ),
        migrations.RemoveConstraint(
            model_name="paymentwebhookreceipt",
            name="payment_webhook_event_unique",
        ),
        migrations.AddConstraint(
            model_name="paymentattempt",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(dispatch_lease_expires_at__isnull=True, dispatch_lease_token__isnull=True)
                    | models.Q(dispatch_lease_expires_at__isnull=False, dispatch_lease_token__isnull=False)
                ),
                name="payment_attempt_lease_complete",
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentwebhookreceipt",
            constraint=models.UniqueConstraint(
                fields=("provider_account", "external_resource_id", "authenticated_request_id_digest"),
                name="payment_webhook_replay_unique",
            ),
        ),
        migrations.RunSQL(IMMUTABLE_SNAPSHOT_TRIGGER, DROP_IMMUTABLE_SNAPSHOT_TRIGGER),
    ]
