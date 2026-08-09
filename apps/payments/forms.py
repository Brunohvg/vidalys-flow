import uuid

from django import forms

from apps.payments.models import PaymentIntent, PaymentProviderAccount


class PaymentFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Busca")
    status = forms.ChoiceField(
        required=False,
        choices=(("", "Todos"), *PaymentIntent.Status.choices),
        label="Estado",
    )


class PaymentIntentCreateForm(forms.Form):
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))


class CheckoutRequestForm(forms.Form):
    provider_account = forms.ModelChoiceField(
        queryset=PaymentProviderAccount.objects.none(),
        label="Provider",
    )
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, organization, payment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider_account"].queryset = PaymentProviderAccount.objects.filter(
            organization=organization,
            is_active=True,
        )
        if not self.is_bound:
            self.initial.setdefault("expected_version", payment.version)
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))

