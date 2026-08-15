import uuid

from django import forms

from apps.fulfillment.pickup_services import PICKUP_CODE_DIGITS


class PickupCompletionForm(forms.Form):
    code = forms.RegexField(
        regex=rf"^\d{{{PICKUP_CODE_DIGITS}}}$",
        max_length=PICKUP_CODE_DIGITS,
        label="Código de retirada",
        error_messages={"invalid": f"Informe os {PICKUP_CODE_DIGITS} dígitos do código de retirada."},
    )
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, fulfillment, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("expected_version", fulfillment.version)
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))
