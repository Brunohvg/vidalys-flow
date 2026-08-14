from django.db import migrations


CREATE_TEMPLATE_GUARD = """
CREATE OR REPLACE FUNCTION messaging_protect_used_template()
RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM messaging_message WHERE template_id = OLD.id
    ) AND ROW(
        NEW.organization_id,
        NEW.semantic_key,
        NEW.name,
        NEW.channel,
        NEW.locale,
        NEW.version,
        NEW.body_text,
        NEW.body_html,
        NEW.parameter_schema,
        NEW.provider_template_reference,
        NEW.is_active
    ) IS DISTINCT FROM ROW(
        OLD.organization_id,
        OLD.semantic_key,
        OLD.name,
        OLD.channel,
        OLD.locale,
        OLD.version,
        OLD.body_text,
        OLD.body_html,
        OLD.parameter_schema,
        OLD.provider_template_reference,
        OLD.is_active
    ) THEN
        RAISE EXCEPTION 'MessageTemplate already used is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER messaging_used_template_immutable
BEFORE UPDATE ON messaging_messagetemplate
FOR EACH ROW EXECUTE FUNCTION messaging_protect_used_template();
"""

DROP_TEMPLATE_GUARD = """
DROP TRIGGER IF EXISTS messaging_used_template_immutable ON messaging_messagetemplate;
DROP FUNCTION IF EXISTS messaging_protect_used_template();
"""

CREATE_MESSAGE_GUARD = """
CREATE OR REPLACE FUNCTION messaging_protect_message_snapshots()
RETURNS trigger AS $$
BEGIN
    IF ROW(
        NEW.organization_id,
        NEW.source_type,
        NEW.source_id,
        NEW.source_version,
        NEW.source_event_id,
        NEW.purpose,
        NEW.template_id,
        NEW.template_semantic_key,
        NEW.template_version,
        NEW.channel_id,
        NEW.channel_kind,
        NEW.locale,
        NEW.customer_id,
        NEW.customer_display_name,
        NEW.contact_point_id,
        NEW.destination_snapshot,
        NEW.permission_evidence_id,
        NEW.permission_policy_version,
        NEW.parameter_snapshot,
        NEW.created_by_id
    ) IS DISTINCT FROM ROW(
        OLD.organization_id,
        OLD.source_type,
        OLD.source_id,
        OLD.source_version,
        OLD.source_event_id,
        OLD.purpose,
        OLD.template_id,
        OLD.template_semantic_key,
        OLD.template_version,
        OLD.channel_id,
        OLD.channel_kind,
        OLD.locale,
        OLD.customer_id,
        OLD.customer_display_name,
        OLD.contact_point_id,
        OLD.destination_snapshot,
        OLD.permission_evidence_id,
        OLD.permission_policy_version,
        OLD.parameter_snapshot,
        OLD.created_by_id
    ) THEN
        RAISE EXCEPTION 'Message snapshots and relationships are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER messaging_message_snapshots_immutable
BEFORE UPDATE ON messaging_message
FOR EACH ROW EXECUTE FUNCTION messaging_protect_message_snapshots();
"""

DROP_MESSAGE_GUARD = """
DROP TRIGGER IF EXISTS messaging_message_snapshots_immutable ON messaging_message;
DROP FUNCTION IF EXISTS messaging_protect_message_snapshots();
"""


class Migration(migrations.Migration):
    dependencies = [("messaging", "0001_initial")]

    operations = [
        migrations.RunSQL(CREATE_TEMPLATE_GUARD, DROP_TEMPLATE_GUARD),
        migrations.RunSQL(CREATE_MESSAGE_GUARD, DROP_MESSAGE_GUARD),
    ]
