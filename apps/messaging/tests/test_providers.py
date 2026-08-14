import pytest

from apps.messaging.exceptions import ProviderEffectsDisabled, UnsafeProviderUrl
from apps.messaging.models import MessagingProviderConnection
from apps.messaging.providers import (
    DisabledProviderAdapter,
    EvolutionAdapter,
    SendRequest,
    SesAdapter,
    WhatsAppCloudAdapter,
    assert_capability,
    evolution_instance_name,
    has_capability,
    map_delivery_status,
    provider_capabilities,
    validate_evolution_url,
    validate_resolved_addresses,
)


def test_evolution_capability_matrix():
    capabilities = provider_capabilities(MessagingProviderConnection.Provider.EVOLUTION)
    assert "linked_device_pairing" in capabilities
    assert "send_text" in capabilities
    assert "delivery_receipts" in capabilities
    assert "message_status_query" in capabilities
    assert "multiple_channels" in capabilities
    assert "official_templates" not in capabilities
    assert "webhook_signature" not in capabilities
    assert "provider_idempotency" not in capabilities


def test_meta_cloud_capability_matrix():
    capabilities = provider_capabilities(MessagingProviderConnection.Provider.WHATSAPP_CLOUD)
    assert "official_templates" in capabilities
    assert "webhook_signature" in capabilities
    assert "linked_device_pairing" not in capabilities
    assert "provider_idempotency" not in capabilities


def test_ses_capability_matrix():
    capabilities = provider_capabilities(MessagingProviderConnection.Provider.SES)
    assert "send_text" in capabilities
    assert "webhook_signature" in capabilities
    assert "linked_device_pairing" not in capabilities
    assert "official_templates" not in capabilities
    assert "provider_idempotency" not in capabilities


def test_assert_capability_fails_closed():
    with pytest.raises(ProviderEffectsDisabled):
        assert_capability(MessagingProviderConnection.Provider.EVOLUTION, "official_templates")
    assert has_capability(MessagingProviderConnection.Provider.EVOLUTION, "linked_device_pairing")


def test_evolution_url_requires_https_and_allowlist():
    url = validate_evolution_url("https://evolution.example.com", allowlist=["evolution.example.com"])
    assert url == "https://evolution.example.com"
    with pytest.raises(UnsafeProviderUrl, match="HTTPS"):
        validate_evolution_url("http://evolution.example.com", allowlist=["evolution.example.com"])
    with pytest.raises(UnsafeProviderUrl, match="allowlist"):
        validate_evolution_url("https://evil.example.com", allowlist=["evolution.example.com"])
    with pytest.raises(UnsafeProviderUrl, match="credenciais"):
        validate_evolution_url("https://user:pass@evolution.example.com", allowlist=["evolution.example.com"])
    with pytest.raises(UnsafeProviderUrl):
        validate_evolution_url("https://127.0.0.1", allowlist=["127.0.0.1"])
    with pytest.raises(UnsafeProviderUrl):
        validate_evolution_url("https://evolution.example.com:8443", allowlist=["evolution.example.com"])


def test_evolution_url_allowlist_subdomain_rule():
    assert validate_evolution_url("https://api.evolution.example.com", allowlist=["evolution.example.com"])
    assert validate_evolution_url("https://evolution.example.com", allowlist=["evolution.example.com"])


def test_resolved_addresses_block_private():
    with pytest.raises(UnsafeProviderUrl, match="privado"):
        validate_resolved_addresses("evolution.example.com", ["10.0.0.1"])
    with pytest.raises(UnsafeProviderUrl, match="privado"):
        validate_resolved_addresses("evolution.example.com", ["127.0.0.1"])
    with pytest.raises(UnsafeProviderUrl):
        validate_resolved_addresses("evolution.example.com", [])
    assert validate_resolved_addresses("evolution.example.com", ["8.8.8.8"])


def test_evolution_instance_name_is_deterministic():
    first = evolution_instance_name(organization_id="org-1", channel_id="ch-1")
    second = evolution_instance_name(organization_id="org-1", channel_id="ch-1")
    different = evolution_instance_name(organization_id="org-2", channel_id="ch-1")
    assert first == second
    assert first != different
    assert first.startswith("vf-")


def _send_request(provider):
    return SendRequest(
        destination="+5511999998888",
        body="Olá",
        body_html="<p>Olá</p>",
        template_reference="order_confirmation",
        provider_correlation_tag="vf:correlation",
        channel_kind="whatsapp",
        provider=provider,
    )


def test_evolution_send_text_contract():
    payload = EvolutionAdapter.contract_payload(_send_request(MessagingProviderConnection.Provider.EVOLUTION))
    assert payload["number"] == "5511999998888"
    assert payload["textMessage"] == {"text": "Olá"}


def test_meta_cloud_send_text_contract():
    payload = WhatsAppCloudAdapter.contract_payload(_send_request(MessagingProviderConnection.Provider.WHATSAPP_CLOUD))
    assert payload["messaging_product"] == "whatsapp"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "order_confirmation"


def test_ses_send_text_contract():
    payload = SesAdapter.contract_payload(_send_request(MessagingProviderConnection.Provider.SES))
    assert payload["Destination"]["ToAddresses"] == ["+5511999998888"]
    assert "Html" in payload["Message"]["Body"]


def test_disabled_adapter_blocks_network():
    adapter = DisabledProviderAdapter()
    with pytest.raises(ProviderEffectsDisabled):
        adapter.send_text(object())
    with pytest.raises(ProviderEffectsDisabled):
        adapter.fetch_status("external-id")


def test_delivery_status_mapping():
    assert map_delivery_status(provider="evolution", status="delivered") == "delivered"
    assert map_delivery_status(provider="evolution", status="read") == "delivered"
    assert map_delivery_status(provider="whatsapp_cloud", status="failed") == "failed"
    assert map_delivery_status(provider="ses", status="bounce") == "failed"
    assert map_delivery_status(provider="ses", status="complaint") == "failed"
    with pytest.raises(UnsafeProviderUrl):
        map_delivery_status(provider="evolution", status="unknown_status")


@pytest.mark.parametrize(
    ("fixture_name", "adapter_class"),
    [
        ("evolution_send_text.json", EvolutionAdapter),
        ("whatsapp_cloud_template.json", WhatsAppCloudAdapter),
        ("ses_send_email.json", SesAdapter),
    ],
)
def test_provider_builders_match_versioned_official_contract_fixtures(fixture_name, adapter_class):
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / "fixtures" / fixture_name
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = SendRequest(**fixture["request"])
    assert adapter_class.contract_payload(request) == fixture["expected_payload"]
    assert fixture["source"].startswith("https://")
