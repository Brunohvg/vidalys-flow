class CustomerDomainError(Exception):
    pass


class CustomerPermissionDenied(CustomerDomainError):
    pass


class CustomerOrganizationMismatch(CustomerDomainError):
    pass


class CustomerMergedError(CustomerDomainError):
    pass


class DuplicateDocumentError(CustomerDomainError):
    pass


class InvalidDocumentError(CustomerDomainError):
    pass


class InvalidMergeError(CustomerDomainError):
    pass


class BlockReasonRequiredError(CustomerDomainError):
    pass
