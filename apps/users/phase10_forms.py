from django import forms

from apps.organizations.models import Membership


class ProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=False, label="Nome")
    last_name = forms.CharField(max_length=150, required=False, label="Sobrenome")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update({"first_name": user.first_name, "last_name": user.last_name})


class MembershipUpdateForm(forms.Form):
    role = forms.ChoiceField(choices=Membership.Role.choices, label="Papel")
    is_active = forms.BooleanField(required=False, label="Acesso ativo")
