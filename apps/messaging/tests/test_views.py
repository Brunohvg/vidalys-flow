import uuid

import pytest
from django.contrib import admin
from django.urls import reverse

from apps.messaging import services
from apps.messaging.admin import MessageAdmin
from apps.messaging.exceptions import InvalidMessage
from apps.messaging.models import (
    Message,
    MessageAutomationRule,
    MessageTemplate,
    MessagingChannel,
    MessagingPreference,
    MessagingProviderConnection,
)
from apps.organizations.models import Membership


def key():
    return str(uuid.uuid4())


@pytest.mark.django_db
def test_pages_require_authentication(client):
    assert client.get(reverse("messaging:list")).status_code == 302


@pytest.mark.django_db
def test_operator_lists_messages_with_masked_destination(
    client,
    organization,
    user,
    operator_membership,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    client.force_login(user)
    response = client.get(reverse("messaging:detail", args=(message.id,)))
    assert response.status_code == 200
    content = response.content.decode()
    assert contact.normalized_value not in content


@pytest.mark.django_db
def test_manager_sees_full_destination(
    client,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    client.force_login(manager)
    response = client.get(reverse("messaging:detail", args=(message.id,)))
    assert response.status_code == 200
    assert contact.normalized_value in response.content.decode()


@pytest.mark.django_db
def test_operator_can_send_manual_message(
    client,
    organization,
    user,
    operator_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    client.force_login(user)
    response = client.post(
        reverse("messaging:send"),
        {
            "source_type": "order",
            "source_id": messaging_order.id,
            "purpose": "order_confirmation",
            "template": whatsapp_template.id,
            "channel": whatsapp_channel.id,
            "contact_point": contact.id,
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    assert Message.objects.count() == 1


@pytest.mark.django_db
def test_operator_cannot_access_configuration(client, organization, user, operator_membership):
    client.force_login(user)
    assert client.get(reverse("messaging:connection_list")).status_code == 404
    assert client.get(reverse("messaging:channel_list")).status_code == 404
    assert client.get(reverse("messaging:template_list")).status_code == 404


@pytest.mark.django_db
def test_manager_accesses_configuration(client, organization, manager, manager_membership):
    client.force_login(manager)
    assert client.get(reverse("messaging:connection_list")).status_code == 200
    assert client.get(reverse("messaging:channel_list")).status_code == 200
    assert client.get(reverse("messaging:template_list")).status_code == 200


@pytest.mark.django_db
def test_cross_organization_message_is_404(
    client,
    organization,
    other_organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    _, contact = messaging_customer
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type=Message.SourceType.ORDER,
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=contact,
        idempotency_key=key(),
    )
    other_user = type(manager).objects.create_user("other-view@example.com", "safe-test-password")
    Membership.objects.create(organization=other_organization, user=other_user, role=Membership.Role.MANAGER)
    client.force_login(other_user)
    assert client.get(reverse("messaging:detail", args=(message.id,))).status_code == 404


@pytest.mark.django_db
def test_callback_endpoint_is_generic_and_disabled_without_secret_channel(client, whatsapp_channel):
    whatsapp_channel.connection.callbacks_enabled = True
    whatsapp_channel.connection.save(update_fields=("callbacks_enabled",))
    url = reverse("messaging:delivery_callback", args=(whatsapp_channel.id,))
    assert client.post(url, data="{}", content_type="text/plain").status_code == 415
    response = client.post(
        url,
        data='{"message_id":"external-message-id","status":"delivered"}',
        content_type="application/json",
        HTTP_X_REQUEST_ID="req",
        HTTP_X_MESSAGING_SECRET="invalid",
    )
    assert response.status_code == 503


@pytest.mark.django_db
def test_callback_endpoint_unknown_channel_is_generic(client):
    response = client.post(
        reverse("messaging:delivery_callback", args=(uuid.uuid4(),)),
        data="{}",
        content_type="application/json",
    )
    assert response.status_code == 202


def test_admin_is_read_only_and_organization_scoped(rf):
    request = rf.get("/admin/")
    message_admin = MessageAdmin(Message, admin.site)
    assert not message_admin.has_add_permission(request)
    assert not message_admin.has_change_permission(request)
    assert not message_admin.has_delete_permission(request)


@pytest.mark.django_db
def test_admin_queryset_and_evidence_permissions_are_organization_scoped(
    rf,
    organization,
    other_organization,
    manager,
    manager_membership,
    outsider,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="order",
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    manager.is_staff = True
    manager.is_superuser = True
    manager.save(update_fields=("is_staff", "is_superuser"))
    request = rf.get("/admin/messaging/message/")
    request.user = manager
    request.session = {}
    message_admin = MessageAdmin(Message, admin.site)
    assert list(message_admin.get_queryset(request)) == [message]
    assert message_admin.has_module_permission(request)
    assert message_admin.has_view_permission(request, message)

    message.organization_id = other_organization.id
    assert not message_admin.has_view_permission(request, message)

    denied = rf.get("/admin/messaging/message/")
    denied.user = outsider
    denied.session = {}
    assert not message_admin.get_queryset(denied).exists()
    assert not message_admin.has_view_permission(denied)


@pytest.mark.django_db
def test_manager_configuration_journey(client, organization, manager, manager_membership, messaging_customer):
    client.force_login(manager)
    response = client.post(
        reverse("messaging:connection_list"),
        {
            "provider": "ses",
            "mode": "email",
            "display_name": "SES candidato",
            "credential_alias": "opaque-ses-alias",
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    connection = MessagingProviderConnection.objects.get(display_name="SES candidato")
    response = client.post(
        reverse("messaging:connection_state", args=(connection.id, "activate")),
        {"expected_version": connection.version, "idempotency_key": key()},
    )
    assert response.status_code == 302
    connection.refresh_from_db()
    assert connection.is_active

    response = client.post(
        reverse("messaging:channel_list"),
        {
            "connection": connection.id,
            "kind": "email",
            "display_name": "E-mail candidato",
            "credential_alias": "opaque-channel-alias",
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    channel = MessagingChannel.objects.get(display_name="E-mail candidato")
    assert channel.state == MessagingChannel.State.INACTIVE
    response = client.post(
        reverse("messaging:channel_activate", args=(channel.id,)),
        {"expected_version": channel.version, "idempotency_key": key()},
    )
    assert response.status_code == 302
    channel.refresh_from_db()
    assert channel.state == MessagingChannel.State.ACTIVE

    response = client.post(
        reverse("messaging:template_list"),
        {
            "semantic_key": "email_order",
            "name": "Pedido por e-mail",
            "channel": "email",
            "locale": "pt-BR",
            "body_text": "Olá {customer_name}, pedido {order_number}.",
            "body_html": "<p>Olá {customer_name}, pedido {order_number}.</p>",
            "parameter_schema": '["customer_name", "order_number"]',
            "provider_template_reference": "",
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    template = MessageTemplate.objects.get(semantic_key="email_order")

    response = client.post(
        reverse("messaging:rule_list"),
        {
            "event_type": "order.confirmed",
            "template": template.id,
            "channel": channel.id,
            "purpose": "order_confirmation",
            "is_enabled": "on",
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    assert MessageAutomationRule.objects.filter(template=template, is_enabled=True).exists()

    email = messaging_customer[0].contacts.get(kind="email")
    response = client.post(
        reverse("messaging:preference_create"),
        {
            "contact_point": email.id,
            "channel": "email",
            "purpose": "order_confirmation",
            "decision": "allowed",
            "provenance": "recorded_consent",
            "policy_version": 1,
            "idempotency_key": key(),
        },
    )
    assert response.status_code == 302
    assert MessagingPreference.objects.filter(contact_point=email, decision="allowed").exists()

    response = client.post(
        reverse("messaging:channel_disable", args=(channel.id,)),
        {"expected_version": channel.version, "idempotency_key": key()},
    )
    assert response.status_code == 302
    channel.refresh_from_db()
    assert channel.state == MessagingChannel.State.DISABLED

    response = client.post(
        reverse("messaging:connection_state", args=(connection.id, "disable")),
        {"expected_version": connection.version, "idempotency_key": key()},
    )
    assert response.status_code == 302
    connection.refresh_from_db()
    assert not connection.is_active


@pytest.mark.django_db
def test_manager_can_cancel_pending_message_from_view(
    client,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="order",
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    client.force_login(manager)
    response = client.post(
        reverse("messaging:cancel", args=(message.id,)),
        {"expected_version": message.version, "idempotency_key": key()},
    )
    assert response.status_code == 302
    message.refresh_from_db()
    assert message.status == Message.Status.CANCELLED


@pytest.mark.django_db
def test_operator_cannot_mutate_configuration_endpoints(client, organization, user, operator_membership):
    client.force_login(user)
    assert client.post(reverse("messaging:connection_list"), {}).status_code == 404
    assert client.post(reverse("messaging:preference_create"), {}).status_code == 404


@pytest.mark.django_db
def test_manager_can_render_every_messaging_form(
    client,
    organization,
    manager,
    manager_membership,
):
    client.force_login(manager)
    for route in (
        "messaging:list",
        "messaging:send",
        "messaging:connection_list",
        "messaging:channel_list",
        "messaging:template_list",
        "messaging:rule_list",
        "messaging:preference_create",
    ):
        assert client.get(reverse(route)).status_code == 200


@pytest.mark.django_db
def test_invalid_configuration_forms_fail_closed_without_writes(
    client,
    organization,
    manager,
    manager_membership,
):
    client.force_login(manager)
    cases = (
        ("messaging:connection_list", MessagingProviderConnection),
        ("messaging:channel_list", MessagingChannel),
        ("messaging:template_list", MessageTemplate),
        ("messaging:rule_list", MessageAutomationRule),
        ("messaging:preference_create", MessagingPreference),
    )
    for route, model in cases:
        before = model.objects.count()
        response = client.post(reverse(route), {})
        assert response.status_code == 200
        assert model.objects.count() == before


@pytest.mark.django_db
def test_invalid_commands_and_unknown_resources_fail_closed(
    client,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="order",
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    client.force_login(manager)
    assert client.post(reverse("messaging:cancel", args=(message.id,)), {}).status_code == 302
    invalid_connection = reverse(
        "messaging:connection_state",
        args=(whatsapp_channel.connection_id, "unknown"),
    )
    assert client.post(invalid_connection, {}).status_code == 404
    unknown_id = uuid.uuid4()
    assert client.post(reverse("messaging:channel_activate", args=(unknown_id,)), {}).status_code == 404
    assert client.post(reverse("messaging:channel_disable", args=(unknown_id,)), {}).status_code == 404
    assert client.post(reverse("messaging:channel_pair", args=(unknown_id,)), {}).status_code == 404


@pytest.mark.django_db
def test_callback_maps_domain_errors_and_acceptance_to_generic_http_statuses(
    client,
    whatsapp_channel,
    monkeypatch,
):
    url = reverse("messaging:delivery_callback", args=(whatsapp_channel.id,))
    monkeypatch.setattr("apps.messaging.views.enforce_callback_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr("apps.messaging.views.process_delivery_callback", lambda **kwargs: None)
    assert client.post(url, data="{}", content_type="application/json").status_code == 202

    def reject(**kwargs):
        raise InvalidMessage("callback inválido")

    monkeypatch.setattr("apps.messaging.views.process_delivery_callback", reject)
    assert client.post(url, data="{}", content_type="application/json").status_code == 400


@pytest.mark.django_db
def test_configuration_views_surface_domain_errors_without_writes(
    client,
    organization,
    manager,
    manager_membership,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    monkeypatch,
):
    client.force_login(manager)

    def reject(**kwargs):
        raise InvalidMessage("contrato rejeitado")

    cases = (
        (
            "create_provider_connection",
            "messaging:connection_list",
            {
                "provider": "ses",
                "mode": "email",
                "display_name": "Inválida",
                "credential_alias": "opaque-alias",
                "idempotency_key": key(),
            },
        ),
        (
            "create_channel",
            "messaging:channel_list",
            {
                "connection": whatsapp_channel.connection_id,
                "kind": "whatsapp",
                "display_name": "Inválido",
                "credential_alias": "opaque-channel",
                "idempotency_key": key(),
            },
        ),
        (
            "create_template",
            "messaging:template_list",
            {
                "semantic_key": "invalid_template",
                "name": "Inválido",
                "channel": "whatsapp",
                "locale": "pt-BR",
                "body_text": "Olá {customer_name}.",
                "body_html": "",
                "parameter_schema": '["customer_name"]',
                "provider_template_reference": "",
                "idempotency_key": key(),
            },
        ),
        (
            "upsert_automation_rule",
            "messaging:rule_list",
            {
                "event_type": "order.confirmed",
                "template": whatsapp_template.id,
                "channel": whatsapp_channel.id,
                "purpose": "order_confirmation",
                "is_enabled": "on",
                "idempotency_key": key(),
            },
        ),
        (
            "record_preference",
            "messaging:preference_create",
            {
                "contact_point": messaging_customer[1].id,
                "channel": "whatsapp",
                "purpose": "order_confirmation",
                "decision": "allowed",
                "provenance": "consent",
                "policy_version": 2,
                "idempotency_key": key(),
            },
        ),
    )
    for service_name, route, payload in cases:
        monkeypatch.setattr(f"apps.messaging.views.services.{service_name}", reject)
        response = client.post(reverse(route), payload)
        assert response.status_code == 200
        assert "contrato rejeitado" in response.content.decode()


@pytest.mark.django_db
def test_command_views_surface_domain_errors(
    client,
    organization,
    manager,
    manager_membership,
    messaging_order,
    messaging_customer,
    whatsapp_template,
    whatsapp_channel,
    allowed_preference,
    monkeypatch,
):
    message = services.create_message_from_command(
        organization=organization,
        actor=manager,
        source_type="order",
        source_id=messaging_order.id,
        purpose="order_confirmation",
        template=whatsapp_template,
        channel=whatsapp_channel,
        contact_point=messaging_customer[1],
        idempotency_key=key(),
    )
    client.force_login(manager)

    def reject(**kwargs):
        raise InvalidMessage("comando rejeitado")

    commands = (
        ("cancel_message", "messaging:cancel", (message.id,), message.version),
        (
            "set_provider_connection_active",
            "messaging:connection_state",
            (whatsapp_channel.connection_id, "disable"),
            whatsapp_channel.connection.version,
        ),
        ("activate_channel", "messaging:channel_activate", (whatsapp_channel.id,), whatsapp_channel.version),
        ("disable_channel", "messaging:channel_disable", (whatsapp_channel.id,), whatsapp_channel.version),
        ("request_pairing", "messaging:channel_pair", (whatsapp_channel.id,), whatsapp_channel.version),
    )
    for service_name, route, args, version in commands:
        monkeypatch.setattr(f"apps.messaging.views.services.{service_name}", reject)
        response = client.post(
            reverse(route, args=args),
            {"expected_version": version, "idempotency_key": key()},
        )
        assert response.status_code == 302
