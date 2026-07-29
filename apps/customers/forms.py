from django import forms

from apps.customers.models import ContactPoint, Customer


class CustomerCreateForm(forms.Form):
    customer_type = forms.ChoiceField(choices=Customer.Type.choices, label="Tipo")
    display_name = forms.CharField(max_length=200, label="Nome")
    legal_name = forms.CharField(max_length=200, required=False, label="Razão social")
    document = forms.CharField(max_length=20, required=False, label="CPF/CNPJ")
    email = forms.EmailField(required=False, label="E-mail principal")
    phone = forms.CharField(max_length=30, required=False, label="Telefone principal")
    notes_summary = forms.CharField(
        max_length=500,
        required=False,
        label="Resumo operacional",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class CustomerEditForm(forms.Form):
    display_name = forms.CharField(max_length=200, label="Nome")
    legal_name = forms.CharField(max_length=200, required=False, label="Razão social")
    notes_summary = forms.CharField(
        max_length=500,
        required=False,
        label="Resumo operacional",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class ContactForm(forms.Form):
    kind = forms.ChoiceField(choices=ContactPoint.Kind.choices, label="Tipo")
    value = forms.CharField(max_length=200, label="Contato")
    is_primary = forms.BooleanField(required=False, label="Principal")


class AddressForm(forms.Form):
    label = forms.CharField(max_length=60, required=False, label="Rótulo")
    recipient_name = forms.CharField(max_length=200, required=False, label="Destinatário")
    postal_code = forms.CharField(max_length=20, required=False, label="CEP")
    street = forms.CharField(max_length=200, label="Logradouro")
    number = forms.CharField(max_length=20, required=False, label="Número")
    complement = forms.CharField(max_length=120, required=False, label="Complemento")
    district = forms.CharField(max_length=120, required=False, label="Bairro")
    city = forms.CharField(max_length=120, label="Cidade")
    state = forms.CharField(max_length=60, label="Estado")
    country = forms.CharField(max_length=2, initial="BR", label="País")
    reference = forms.CharField(max_length=200, required=False, label="Referência")
    is_default_shipping = forms.BooleanField(required=False, label="Padrão de entrega")
    is_default_billing = forms.BooleanField(required=False, label="Padrão de cobrança")


class NoteForm(forms.Form):
    content = forms.CharField(max_length=1000, label="Nota", widget=forms.Textarea(attrs={"rows": 3}))


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Customer.Status.choices, label="Status")
    reason = forms.CharField(max_length=500, required=False, label="Motivo")


class MergeForm(forms.Form):
    target_id = forms.UUIDField(label="Cliente destino")
    reason = forms.CharField(max_length=500, label="Motivo", widget=forms.Textarea(attrs={"rows": 3}))
