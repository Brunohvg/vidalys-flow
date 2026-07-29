from apps.audit.models import AuditEvent

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "credential",
    "key",
    "password",
    "secret",
    "token",
}
REDACTED = "[REDACTED]"


def sanitize_payload(value):
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else sanitize_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _is_sensitive_key(key):
    normalized = str(key).lower().replace("-", "_")
    return any(part in SENSITIVE_KEYS for part in normalized.split("_"))


def record_event(
    *,
    organization,
    action,
    entity_type,
    entity_id,
    actor=None,
    payload=None,
    correlation_id=None,
):
    return AuditEvent.objects.create(
        organization=organization,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload=sanitize_payload(payload or {}),
        correlation_id=correlation_id,
    )
