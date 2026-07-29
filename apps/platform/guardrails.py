from django.conf import settings

from apps.core.exceptions import VidalysFlowError


class ExternalEffectBlockedError(VidalysFlowError):
    pass


def external_effects_blocked():
    return bool(settings.VIDALYS_DEMO_MODE)


def require_external_effects_allowed():
    if external_effects_blocked():
        raise ExternalEffectBlockedError("Efeitos externos estão bloqueados pela configuração do ambiente.")
