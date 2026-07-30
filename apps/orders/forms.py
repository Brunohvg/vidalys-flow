import uuid
from decimal import Decimal

from django import forms

from apps.customers.models import Customer
from apps.orders.models import Order
from apps.products.models import Product, ProductVariant


class IdempotentVersionedForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    @staticmethod
    def command_initial(*, version):
        return {"expected_version": version, "idempotency_key": str(uuid.uuid4())}


class OrderCreateForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), label="Cliente")
    channel = forms.CharField(max_length=40, required=False, label="Canal")
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            organization=organization,
            merged_into__isnull=True,
            status=Customer.Status.ACTIVE,
        )
        if not self.is_bound:
            self.initial["idempotency_key"] = str(uuid.uuid4())


class CustomerChangeForm(IdempotentVersionedForm):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), label="Cliente canônico")

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            organization=organization,
            merged_into__isnull=True,
            status=Customer.Status.ACTIVE,
        )


class ItemCreateForm(IdempotentVersionedForm):
    product = forms.ModelChoiceField(queryset=Product.objects.none(), required=False, label="Produto")
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.none(), required=False, label="Variação")
    name = forms.CharField(max_length=200, required=False, label="Nome do item avulso")
    unit = forms.CharField(max_length=20, initial="un", label="Unidade do item avulso")
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        initial=1,
        label="Quantidade",
    )
    unit_price = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, label="Preço-base")
    discount_amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=0,
        initial=0,
        label="Desconto",
    )
    surcharge_amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=0,
        initial=0,
        label="Acréscimo",
    )
    surcharge_reason = forms.CharField(max_length=500, required=False, label="Motivo do acréscimo")
    notes = forms.CharField(max_length=500, required=False, label="Observação operacional")

    def __init__(self, *args, organization, can_adjust, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            organization=organization,
            status=Product.Status.ACTIVE,
        )
        self.fields["variant"].queryset = ProductVariant.objects.filter(
            organization=organization,
            status=Product.Status.ACTIVE,
            product__status=Product.Status.ACTIVE,
        ).select_related("product")
        if not can_adjust:
            self.fields["discount_amount"].disabled = True
            self.fields["surcharge_amount"].disabled = True
            self.fields["surcharge_reason"].disabled = True


class ItemUpdateForm(IdempotentVersionedForm):
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        label="Quantidade",
    )
    unit_price = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, label="Preço-base")
    discount_amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, label="Desconto")
    surcharge_amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, label="Acréscimo")
    surcharge_reason = forms.CharField(max_length=500, required=False, label="Motivo do acréscimo")
    notes = forms.CharField(max_length=500, required=False, label="Observação operacional")

    def __init__(self, *args, can_adjust, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_adjust:
            self.fields["discount_amount"].disabled = True
            self.fields["surcharge_amount"].disabled = True
            self.fields["surcharge_reason"].disabled = True


class CommandForm(IdempotentVersionedForm):
    pass


class CancelForm(IdempotentVersionedForm):
    reason = forms.CharField(max_length=500, label="Motivo", widget=forms.Textarea(attrs={"rows": 3}))


class OrderFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Busca")
    status = forms.ChoiceField(
        required=False,
        choices=(("", "Todos"), *Order.Status.choices),
        label="Estado",
    )
    channel = forms.CharField(max_length=40, required=False, label="Canal")
    created_from = forms.DateField(required=False, label="De", widget=forms.DateInput(attrs={"type": "date"}))
    created_to = forms.DateField(required=False, label="Até", widget=forms.DateInput(attrs={"type": "date"}))
