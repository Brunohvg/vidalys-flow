from apps.core.exceptions import VidalysFlowError


class MessagingDomainError(VidalysFlowError):
    pass


class InvalidMessage(MessagingDomainError):
    pass


class MessagingPermissionDenied(MessagingDomainError):
    pass


class OrganizationMismatch(MessagingDomainError):
    pass


class IdempotencyConflict(MessagingDomainError):
    pass


class VersionConflict(MessagingDomainError):
    pass


class ProviderEffectsDisabled(MessagingDomainError):
    pass


class CallbackRejected(MessagingDomainError):
    pass


class UnsafeProviderUrl(MessagingDomainError):
    pass
