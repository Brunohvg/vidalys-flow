import uuid

from django import forms

from apps.payments.manual_services import MANUAL_PAYMENT_METHODS


class ManualPaymentForm(forms.Form):
    method = forms.ChoiceField(
        choices=tuple(MANUAL_PAYMENT_METHODS.items()),
        label="Forma de pagamento",
    )
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01, label="Valor recebido")
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, payment, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("amount", payment.amount)
            self.initial.setdefault("expected_version", payment.version)
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))
