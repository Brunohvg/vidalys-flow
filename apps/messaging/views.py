from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.messaging import policies, selectors, services
from apps.messaging.callbacks import enforce_callback_rate_limit, process_delivery_callback
from apps.messaging.exceptions import MessagingDomainError, ProviderEffectsDisabled
from apps.messaging.forms import (
    AutomationRuleForm,
    ChannelCommandForm,
    ChannelCreateForm,
    ConnectionCommandForm,
    ConnectionCreateForm,
    MessageFilterForm,
    MessageSendForm,
    PreferenceForm,
    TemplateCreateForm,
)
from apps.messaging.models import MessagingChannel
from apps.organizations.selectors import active_organization_for_user


def _context_or_redirect(request):
    organization, membership = active_organization_for_user(user=request.user, session=request.session)
    if organization and policies.can_view_messages(user=request.user, organization=organization):
        return organization, membership
    messages.info(request, "Selecione uma organização ativa para continuar.")
    return redirect("organizations:list")


def _message_or_404(*, organization, message_id):
    message = selectors.message_for_organization(organization=organization, message_id=message_id)
    if message is None:
        raise Http404
    return message


@login_required
def message_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, membership = context
    form = MessageFilterForm(request.GET or None)
    filters = form.cleaned_data if form.is_valid() else {}
    if "q" in filters:
        filters["query"] = filters.pop("q")
    messages_qs = Paginator(selectors.search_messages(organization=organization, **filters), 25).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "messaging/message_list.html",
        {"organization": organization, "messages": messages_qs, "filter_form": form},
    )


@login_required
def message_detail(request, message_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, membership = context
    message = _message_or_404(organization=organization, message_id=message_id)
    return render(
        request,
        "messaging/message_detail.html",
        {
            "organization": organization,
            "message": message,
            "detail": selectors.message_detail(
                organization=organization,
                message=message,
                user=request.user,
                membership=membership,
            ),
            "cancel_form": ChannelCommandForm(version=message.version),
            "can_configure": policies.can_configure_messaging(user=request.user, organization=organization),
        },
    )


@login_required
def message_send(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    form = MessageSendForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_message_from_command(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Mensagem transacional registrada sem chamada externa.")
            return redirect("messaging:list")
    return render(request, "messaging/message_send.html", {"organization": organization, "form": form})


@login_required
@require_POST
def message_cancel(request, message_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    message = _message_or_404(organization=organization, message_id=message_id)
    form = ChannelCommandForm(request.POST, version=message.version)
    if form.is_valid():
        try:
            services.cancel_message(
                organization=organization,
                actor=request.user,
                message=message,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Mensagem cancelada.")
    else:
        messages.error(request, "Comando de cancelamento inválido.")
    return redirect("messaging:detail", message_id=message.id)


@login_required
def connection_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    if not policies.can_configure_messaging(user=request.user, organization=organization):
        raise Http404
    connections = selectors.connections_for_organization(organization=organization)
    form = ConnectionCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_provider_connection(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Conexão de provider criada.")
            return redirect("messaging:connection_list")
    return render(
        request,
        "messaging/connection_list.html",
        {
            "organization": organization,
            "connections": connections,
            "form": form,
            "command_forms": {
                connection.id: ConnectionCommandForm(version=connection.version) for connection in connections
            },
        },
    )


@login_required
@require_POST
def connection_state(request, connection_id, action):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    connection = selectors.connections_for_organization(organization=organization).filter(id=connection_id).first()
    if connection is None or action not in {"activate", "disable"}:
        raise Http404
    form = ConnectionCommandForm(request.POST, version=connection.version)
    if form.is_valid():
        try:
            services.set_provider_connection_active(
                organization=organization,
                actor=request.user,
                connection=connection,
                is_active=action == "activate",
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Estado da conexão atualizado.")
    else:
        messages.error(request, "Comando de conexão inválido.")
    return redirect("messaging:connection_list")


@login_required
def channel_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    if not policies.can_configure_messaging(user=request.user, organization=organization):
        raise Http404
    channels = selectors.channels_for_organization(organization=organization)
    form = ChannelCreateForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_channel(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Canal criado.")
            return redirect("messaging:channel_list")
    return render(
        request,
        "messaging/channel_list.html",
        {"organization": organization, "channels": channels, "form": form},
    )


@login_required
@require_POST
def channel_activate(request, channel_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    channel = MessagingChannel.objects.filter(organization=organization, id=channel_id).first()
    if channel is None:
        raise Http404
    form = ChannelCommandForm(request.POST, version=channel.version)
    if form.is_valid():
        try:
            services.activate_channel(
                organization=organization,
                actor=request.user,
                channel=channel,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Canal ativado.")
    return redirect("messaging:channel_list")


@login_required
@require_POST
def channel_disable(request, channel_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    channel = MessagingChannel.objects.filter(organization=organization, id=channel_id).first()
    if channel is None:
        raise Http404
    form = ChannelCommandForm(request.POST, version=channel.version)
    if form.is_valid():
        try:
            services.disable_channel(
                organization=organization,
                actor=request.user,
                channel=channel,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Canal desabilitado.")
    return redirect("messaging:channel_list")


@login_required
@require_POST
def channel_pair(request, channel_id):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    channel = MessagingChannel.objects.filter(organization=organization, id=channel_id).first()
    if channel is None:
        raise Http404
    form = ChannelCommandForm(request.POST, version=channel.version)
    if form.is_valid():
        try:
            services.request_pairing(
                organization=organization,
                actor=request.user,
                channel=channel,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Pareamento registrado.")
    return redirect("messaging:channel_list")


@login_required
def template_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    if not policies.can_configure_messaging(user=request.user, organization=organization):
        raise Http404
    templates = selectors.templates_for_organization(organization=organization)
    form = TemplateCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_template(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Template criado.")
            return redirect("messaging:template_list")
    return render(
        request,
        "messaging/template_list.html",
        {"organization": organization, "templates": templates, "form": form},
    )


@login_required
def rule_list(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    if not policies.can_configure_messaging(user=request.user, organization=organization):
        raise Http404
    rules = services.MessageAutomationRule.objects.filter(organization=organization).select_related(
        "template", "channel"
    )
    form = AutomationRuleForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            services.upsert_automation_rule(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Regra de automação registrada.")
            return redirect("messaging:rule_list")
    return render(request, "messaging/rule_list.html", {"organization": organization, "rules": rules, "form": form})


@login_required
def preference_create(request):
    context = _context_or_redirect(request)
    if not isinstance(context, tuple):
        return context
    organization, _ = context
    if not policies.can_configure_messaging(user=request.user, organization=organization):
        raise Http404
    form = PreferenceForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            services.record_preference(
                organization=organization,
                actor=request.user,
                **form.cleaned_data,
            )
        except MessagingDomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Preferência registrada.")
            return redirect("messaging:preference_create")
    return render(request, "messaging/preference_form.html", {"organization": organization, "form": form})


@csrf_exempt
@require_POST
def delivery_callback(request, channel_id):
    if request.content_type != "application/json":
        return HttpResponse(status=415)
    channel = (
        MessagingChannel.objects.select_related("connection", "connection__organization").filter(id=channel_id).first()
    )
    if channel is None:
        return HttpResponse(status=202)
    try:
        enforce_callback_rate_limit(
            channel_id=channel.id,
            remote_address=request.META.get("REMOTE_ADDR", "unknown"),
        )
        process_delivery_callback(
            channel=channel,
            raw_body=request.body,
            request_id=request.headers.get("X-Request-Id", ""),
            signature_header=request.headers.get("X-Messaging-Secret", ""),
        )
    except ProviderEffectsDisabled:
        return HttpResponse(status=503)
    except MessagingDomainError:
        return HttpResponse(status=400)
    return HttpResponse(status=202)
