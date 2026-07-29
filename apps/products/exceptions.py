class ProductDomainError(Exception):
    pass


class ProductPermissionDenied(ProductDomainError):
    pass


class ProductOrganizationMismatch(ProductDomainError):
    pass


class DuplicateSkuError(ProductDomainError):
    pass


class DuplicateBarcodeError(ProductDomainError):
    pass


class DuplicateIdentifierError(ProductDomainError):
    pass


class VariantProductMismatch(ProductDomainError):
    pass
