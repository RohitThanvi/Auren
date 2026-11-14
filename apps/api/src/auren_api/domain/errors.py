"""Domain-level errors. The HTTP layer maps them to responses; services never import HTTP."""


class DomainError(Exception):
    """A violated business rule. ``code`` is a stable machine-readable identifier."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class RuleViolationError(DomainError):
    """The request is well-formed but breaks a business rule (maps to 422)."""


class ConflictViolationError(DomainError):
    """The request conflicts with current state (maps to 409)."""


class ResourceNotFoundError(DomainError):
    """The resource does not exist or is not visible to the caller (maps to 404)."""
