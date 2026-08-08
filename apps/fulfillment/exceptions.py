class FulfillmentDomainError(Exception):
    pass


class FulfillmentPermissionDenied(FulfillmentDomainError):
    pass


class OrganizationMismatch(FulfillmentDomainError):
    pass


class InvalidFulfillment(FulfillmentDomainError):
    pass


class InvalidTransition(FulfillmentDomainError):
    pass


class VersionConflict(FulfillmentDomainError):
    pass


class IdempotencyConflict(FulfillmentDomainError):
    pass


class ReasonRequired(FulfillmentDomainError):
    pass
