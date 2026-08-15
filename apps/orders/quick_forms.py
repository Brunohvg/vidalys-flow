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
    delivery_postal_code = forms.CharField(max_length=9, required=False, label="CEP")
    delivery_street = forms.CharField(max_length=200, required=False, label="Rua")
    delivery_number = forms.CharField(max_length=30, required=False, label="Número")
    delivery_complement = forms.CharField(max_length=120, required=False, label="Complemento")
    delivery_district = forms.CharField(max_length=120, required=False, label="Bairro")
    delivery_city = forms.CharField(max_length=120, required=False, label="Cidade")
    delivery_state = forms.CharField(max_length=2, required=False, label="UF")
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

        address_fields = (
            "delivery_postal_code",
            "delivery_street",
            "delivery_number",
            "delivery_complement",
            "delivery_district",
            "delivery_city",
            "delivery_state",
        )
        has_delivery_address = any((cleaned.get(field) or "").strip() for field in address_fields)
        cleaned["has_delivery_address"] = has_delivery_address
        if has_delivery_address:
            for field in ("delivery_postal_code", "delivery_street", "delivery_city", "delivery_state"):
                if not (cleaned.get(field) or "").strip():
                    self.add_error(field, "Campo obrigatório para endereço de entrega.")
            postal_code = "".join(
                character
                for character in (cleaned.get("delivery_postal_code") or "")
                if character.isdigit()
            )
            if postal_code and len(postal_code) != 8:
                self.add_error("delivery_postal_code", "CEP deve conter 8 dígitos.")
            else:
                cleaned["delivery_postal_code"] = postal_code
            state = (cleaned.get("delivery_state") or "").strip().upper()
            if state and len(state) != 2:
                self.add_error("delivery_state", "UF deve conter 2 letras.")
            cleaned["delivery_state"] = state
        return cleaned
