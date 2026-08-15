import uuid
from decimal import Decimal

from django import forms

from apps.customers.models import Customer
from apps.orders.models import Order


class QuickOrderCreateForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=False,
        label="Cliente existente",
        help_text="Selecione quando o cliente já estiver cadastrado.",
    )
    customer_name = forms.CharField(max_length=200, required=False, label="Nome do cliente")
    customer_document = forms.CharField(max_length=18, required=False, label="CPF/CNPJ")
    customer_phone = forms.CharField(max_length=32, required=False, label="Telefone/WhatsApp")
    customer_email = forms.EmailField(required=False, label="E-mail")
    pricing_mode = forms.ChoiceField(
        choices=Order.PricingMode.choices,
        initial=Order.PricingMode.MANUAL,
        label="Como informar o valor",
    )
    manual_total = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
        label="Valor da venda",
    )
    channel = forms.CharField(max_length=40, required=False, label="Canal")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            organization=organization,
            merged_into__isnull=True,
            status=Customer.Status.ACTIVE,
        ).order_by("display_name")
        if not self.is_bound:
            self.initial["idempotency_key"] = str(uuid.uuid4())

    def clean(self):
        cleaned = super().clean()
        customer = cleaned.get("customer")
        customer_name = (cleaned.get("customer_name") or "").strip()
        pricing_mode = cleaned.get("pricing_mode")
        manual_total = cleaned.get("manual_total")

        if customer is None and not customer_name:
            self.add_error("customer_name", "Selecione um cliente existente ou informe o nome do novo cliente.")

        if pricing_mode == Order.PricingMode.MANUAL and manual_total is None:
            self.add_error("manual_total", "Informe o valor da venda.")
        if pricing_mode == Order.PricingMode.ITEMIZED:
            cleaned["manual_total"] = None
        return cleaned
