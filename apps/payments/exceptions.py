from apps.core.exceptions import VidalysFlowError


class PaymentDomainError(VidalysFlowError):
    pass


class InvalidPayment(PaymentDomainError):
    pass


class PaymentPermissionDenied(PaymentDomainError):
    pass


class OrganizationMismatch(PaymentDomainError):
    pass


class IdempotencyConflict(PaymentDomainError):
    pass


class VersionConflict(PaymentDomainError):
    pass


class ProviderEffectsDisabled(PaymentDomainError):
    pass


class CallbackRejected(PaymentDomainError):
    pass
