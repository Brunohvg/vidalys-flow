class FulfillmentDomainError(Exception):
    pass


class OrganizationMismatch(FulfillmentDomainError):
    pass


class IdempotencyConflict(FulfillmentDomainError):
    pass


class QuantityExceeded(FulfillmentDomainError):
    pass


class PermissionDenied(FulfillmentDomainError):
    pass


class VersionConflict(FulfillmentDomainError):
    pass


class ReasonRequired(FulfillmentDomainError):
    pass
