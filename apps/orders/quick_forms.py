import uuid
from decimal import Decimal

from django import forms

from apps.customers.models import Customer
from apps.fulfillment.models import Fulfillment
from apps.orders.models import Order
from apps.organizations.models import OrganizationUnit
from apps.products.models import Product, ProductVariant


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
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label="Produto",
        help_text="Opcional para venda por valor; obrigatório no modo por itens.",
    )
    variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.none(),
        required=False,
        label="Variação",
        help_text="Opcional. SKU e código de barras selecionam a variação exata.",
    )
    product_quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        initial=Decimal("1.000"),
        required=False,
        label="Quantidade",
    )
    product_unit_price = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        label="Preço unitário",
    )
    fulfillment_method = forms.ChoiceField(
        choices=Fulfillment.Method.choices,
        initial=Fulfillment.Method.PICKUP,
        label="Atendimento",
    )
    pickup_unit = forms.ModelChoiceField(
        queryset=OrganizationUnit.objects.none(),
        required=False,
        label="Unidade de retirada",
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
        self.fields["product"].queryset = Product.objects.filter(
            organization=organization,
            status=Product.Status.ACTIVE,
        ).order_by("name")
        self.fields["variant"].queryset = ProductVariant.objects.filter(
            organization=organization,
            status=Product.Status.ACTIVE,
            product__status=Product.Status.ACTIVE,
        ).select_related("product").order_by("product__name", "name", "sku")
        self.fields["pickup_unit"].queryset = OrganizationUnit.objects.filter(
            organization=organization,
            is_active=True,
        ).order_by("name")
        if not self.is_bound:
            self.initial["idempotency_key"] = str(uuid.uuid4())

    def clean(self):
        cleaned = super().clean()
        customer = cleaned.get("customer")
        customer_name = (cleaned.get("customer_name") or "").strip()
        pricing_mode = cleaned.get("pricing_mode")
        manual_total = cleaned.get("manual_total")
        product = cleaned.get("product")
        variant = cleaned.get("variant")
        product_quantity = cleaned.get("product_quantity")
        product_unit_price = cleaned.get("product_unit_price")
        method = cleaned.get("fulfillment_method")
        pickup_unit = cleaned.get("pickup_unit")

        if customer is None and not customer_name:
            self.add_error("customer_name", "Selecione um cliente existente ou informe o nome do novo cliente.")

        if variant is not None:
            if product is None:
                product = variant.product
                cleaned["product"] = product
            elif variant.product_id != product.id:
                self.add_error("variant", "A variação selecionada não pertence ao produto.")

        if pricing_mode == Order.PricingMode.MANUAL and manual_total is None:
            self.add_error("manual_total", "Informe o valor da venda.")
        if pricing_mode == Order.PricingMode.ITEMIZED:
            cleaned["manual_total"] = None
            if product is None:
                self.add_error("product", "Venda por itens exige ao menos um produto na jornada rápida.")

        if product is not None:
            if product_quantity is None:
                self.add_error("product_quantity", "Informe a quantidade.")
            if product_unit_price is None:
                self.add_error("product_unit_price", "Informe o preço unitário.")
        else:
            cleaned["variant"] = None
            cleaned["product_quantity"] = None
            cleaned["product_unit_price"] = None

        address_fields = (
            "delivery_postal_code",
            "delivery_street",
            "delivery_number",
            "delivery_complement",
            "delivery_district",
            "delivery_city",
            "delivery_state",
        )
        has_any_address = any((cleaned.get(field) or "").strip() for field in address_fields)
        is_delivery = method == Fulfillment.Method.DELIVERY
        cleaned["has_delivery_address"] = is_delivery

        if method == Fulfillment.Method.PICKUP:
            if pickup_unit is None:
                self.add_error("pickup_unit", "Retirada exige uma unidade ativa.")
            if has_any_address:
                self.add_error("fulfillment_method", "Endereço de entrega não deve ser informado para retirada.")
        elif is_delivery:
            if pickup_unit is not None:
                self.add_error("pickup_unit", "Entrega não utiliza unidade de retirada.")
            for field in ("delivery_postal_code", "delivery_street", "delivery_city", "delivery_state"):
                if not (cleaned.get(field) or "").strip():
                    self.add_error(field, "Campo obrigatório para entrega.")
        else:
            self.add_error("fulfillment_method", "Selecione Retirada ou Entrega.")

        if is_delivery:
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
