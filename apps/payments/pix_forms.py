from django import forms

from apps.payments.models import PixPaymentInstruction


class PixInstructionForm(forms.Form):
    key_type = forms.ChoiceField(choices=PixPaymentInstruction.KeyType.choices, label="Tipo da chave")
    key_value = forms.CharField(max_length=160, label="Chave PIX")
    beneficiary_name = forms.CharField(max_length=200, label="Favorecido")
    bank_name = forms.CharField(max_length=120, required=False, label="Banco (opcional)")
    is_active = forms.BooleanField(required=False, initial=True, label="Disponível para cobrança")
    expected_version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, instruction=None, **kwargs):
        super().__init__(*args, **kwargs)
        if instruction is not None and not self.is_bound:
            self.initial.update(
                {
                    "key_type": instruction.key_type,
                    "key_value": instruction.key_value,
                    "beneficiary_name": instruction.beneficiary_name,
                    "bank_name": instruction.bank_name,
                    "is_active": instruction.is_active,
                    "expected_version": instruction.version,
                }
            )
