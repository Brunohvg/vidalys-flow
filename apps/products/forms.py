from django import forms

from apps.products.models import Product, ProductIdentifier


class ProductForm(forms.Form):
    name = forms.CharField(max_length=200, label="Nome")
    description = forms.CharField(
        required=False,
        label="Descrição",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    default_unit = forms.CharField(max_length=20, initial="un", label="Unidade")


class VariantForm(forms.Form):
    name = forms.CharField(max_length=200, required=False, label="Variação")
    sku = forms.CharField(max_length=64, required=False, label="SKU")
    barcode = forms.CharField(max_length=64, required=False, label="Código de barras")


class IdentifierForm(forms.Form):
    kind = forms.ChoiceField(choices=ProductIdentifier.Kind.choices, label="Tipo")
    value = forms.CharField(max_length=200, label="Valor")


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Product.Status.choices, label="Status")
    reason = forms.CharField(max_length=500, required=False, label="Motivo")
