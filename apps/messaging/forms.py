import uuid

from django import forms

from apps.messaging.models import Message, MessageTemplate, MessagingChannel, MessagingProviderConnection

PURPOSE_CHOICES = (
    ("order_confirmation", "Confirmação de pedido"),
    ("fulfillment_progress", "Progresso de fulfillment"),
    ("payment_confirmation", "Confirmação de pagamento"),
    ("checkout_link", "Link de checkout"),
    ("pix_instruction", "Instrução PIX"),
)


class MessageFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Busca")
    status = forms.ChoiceField(required=False, choices=(("", "Todos"), *Message.Status.choices), label="Estado")


class MessageSendForm(forms.Form):
    source_type = forms.ChoiceField(choices=Message.SourceType.choices, label="Fonte")
    source_id = forms.UUIDField(label="Identificador da fonte")
    purpose = forms.ChoiceField(choices=PURPOSE_CHOICES, label="Finalidade")
    template = forms.ModelChoiceField(queryset=MessageTemplate.objects.none(), label="Template")
    channel = forms.ModelChoiceField(queryset=MessagingChannel.objects.none(), label="Canal")
    contact_point = forms.ModelChoiceField(queryset=MessageTemplate.objects.none(), label="Contato")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.customers.models import ContactPoint

        self.fields["template"].queryset = MessageTemplate.objects.filter(organization=organization, is_active=True)
        self.fields["channel"].queryset = MessagingChannel.objects.filter(
            organization=organization, state=MessagingChannel.State.ACTIVE
        )
        self.fields["contact_point"].queryset = ContactPoint.objects.filter(
            customer__organization=organization, is_active=True
        )
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class ConnectionCreateForm(forms.Form):
    provider = forms.ChoiceField(choices=MessagingProviderConnection.Provider.choices, label="Provider")
    mode = forms.ChoiceField(choices=MessagingProviderConnection.Mode.choices, label="Modo")
    display_name = forms.CharField(max_length=120, label="Nome")
    credential_alias = forms.CharField(max_length=120, label="Alias de credencial")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class ChannelCreateForm(forms.Form):
    connection = forms.ModelChoiceField(queryset=MessagingProviderConnection.objects.none(), label="Conexão")
    kind = forms.ChoiceField(choices=MessagingProviderConnection.Provider.choices, label="Tipo")
    display_name = forms.CharField(max_length=120, label="Nome")
    credential_alias = forms.CharField(max_length=120, label="Alias de credencial do canal")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["connection"].queryset = MessagingProviderConnection.objects.filter(
            organization=organization, is_active=True
        )
        self.fields["kind"].choices = MessagingChannel.Kind.choices
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class ChannelCommandForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("expected_version", version)
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class ConnectionCommandForm(ChannelCommandForm):
    pass


class TemplateCreateForm(forms.Form):
    semantic_key = forms.CharField(max_length=120, label="Chave semântica")
    name = forms.CharField(max_length=200, label="Nome")
    channel = forms.ChoiceField(choices=MessageTemplate.Channel.choices, label="Canal")
    locale = forms.CharField(max_length=20, initial="pt-BR", label="Locale")
    body_text = forms.CharField(widget=forms.Textarea, label="Corpo de texto")
    body_html = forms.CharField(widget=forms.Textarea, required=False, label="Corpo HTML (e-mail)")
    parameter_schema = forms.JSONField(required=False, label="Schema de parâmetros (JSON)")
    provider_template_reference = forms.CharField(max_length=200, required=False, label="Referência no provider")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("parameter_schema", [])
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class AutomationRuleForm(forms.Form):
    event_type = forms.ChoiceField(
        choices=(
            ("order.confirmed", "Pedido confirmado"),
            ("fulfillment.ready", "Fulfillment pronto"),
            ("fulfillment.dispatched", "Fulfillment despachado"),
            ("fulfillment.completed", "Fulfillment concluído"),
            ("payment.checkout_activated", "Checkout ativado"),
            ("payment.status_changed", "Pagamento pago"),
        ),
        label="Evento",
    )
    event_version = forms.IntegerField(min_value=1, initial=1, label="Versão do contrato do evento")
    template = forms.ModelChoiceField(queryset=MessageTemplate.objects.none(), label="Template")
    channel = forms.ModelChoiceField(queryset=MessagingChannel.objects.none(), label="Canal")
    purpose = forms.ChoiceField(choices=PURPOSE_CHOICES, label="Finalidade")
    is_enabled = forms.BooleanField(required=False, label="Habilitado")
    expected_version = forms.IntegerField(
        required=False,
        min_value=1,
        label="Versão esperada (obrigatória ao atualizar)",
    )
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = MessageTemplate.objects.filter(organization=organization, is_active=True)
        self.fields["channel"].queryset = MessagingChannel.objects.filter(organization=organization)
        if not self.is_bound:
            self.initial.setdefault("event_version", 1)
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class PreferenceForm(forms.Form):
    contact_point = forms.ModelChoiceField(queryset=MessageTemplate.objects.none(), label="Contato")
    channel = forms.ChoiceField(choices=MessageTemplate.Channel.choices, label="Canal")
    purpose = forms.ChoiceField(choices=PURPOSE_CHOICES, label="Finalidade")
    decision = forms.ChoiceField(
        choices=(("allowed", "Permitido"), ("suppressed", "Suprimido")),
        label="Decisão",
    )
    provenance = forms.CharField(max_length=120, label="Proveniência")
    policy_version = forms.IntegerField(min_value=1, initial=1, label="Versão da política")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.customers.models import ContactPoint

        self.fields["contact_point"].queryset = ContactPoint.objects.filter(
            customer__organization=organization, is_active=True
        )
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))
