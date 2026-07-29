from apps.core.exceptions import VidalysFlowError


class OrganizationError(VidalysFlowError):
    pass


class LastActiveOwnerError(OrganizationError):
    pass


class BootstrapConflictError(OrganizationError):
    pass
