class IntegrationError(Exception):
    """Base error for the provider-neutral integration boundary."""


class IntegrationContractError(IntegrationError):
    pass


class IntegrationAuthorizationError(IntegrationError):
    pass


class IntegrationTransientError(IntegrationError):
    pass


class IntegrationPermanentError(IntegrationError):
    pass


class IntegrationAmbiguousError(IntegrationError):
    pass
