class OrderDomainError(Exception):
    pass


class OrderPermissionDenied(OrderDomainError):
    pass


class OrganizationMismatch(OrderDomainError):
    pass


class OrderNotEditable(OrderDomainError):
    pass


class VersionConflict(OrderDomainError):
    pass


class IdempotencyConflict(OrderDomainError):
    pass


class InvalidItem(OrderDomainError):
    pass


class InvalidTransition(OrderDomainError):
    pass


class ConfirmationBlocked(OrderDomainError):
    pass


class ReasonRequired(OrderDomainError):
    pass
