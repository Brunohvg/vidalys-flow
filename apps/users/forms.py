from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "E-mail ou senha inválidos.",
        "inactive": "Esta conta está inativa.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
