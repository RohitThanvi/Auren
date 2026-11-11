"""Application error hierarchy and the single public error format.

Every error response has the shape ``{"error": {"code", "message", "request_id", "details"}}``.
Internal exception text is never exposed to clients.
"""

from collections.abc import Mapping, Sequence

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from auren_api.schemas.common import ErrorBody, ErrorDetail, ErrorResponse

logger = structlog.get_logger(__name__)


class AppError(StarletteHTTPException):
    """Base class for expected, client-visible errors.

    Subclasses ``HTTPException`` so that FastAPI propagates it unchanged even when it is raised
    while the request body is being read (otherwise it would be rewritten into a generic 400).
    """

    status_code: int = 500
    code: str = "internal_error"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        details: Sequence[ErrorDetail] = (),
    ) -> None:
        resolved = message or self.default_message
        super().__init__(
            status_code=type(self).status_code, detail=resolved, headers=dict(headers or {})
        )
        self.message = resolved
        self.details = list(details)


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Authentication is required."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "The requested resource was not found."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    default_message = "The request body is too large."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    default_message = "Too many requests."

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(headers={"Retry-After": str(max(1, retry_after_seconds))})


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    default_message = "The service is temporarily unavailable."


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Sequence[ErrorDetail] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=request_id if isinstance(request_id, str) else None,
            details=list(details),
        )
    )
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=dict(headers or {})
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(
                location=[str(part) for part in item["loc"]],
                message=str(item["msg"]),
                type=str(item["type"]),
            )
            for item in exc.errors()
        ]
        return error_response(
            status_code=422,
            code="validation_error",
            message="The request is invalid.",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            headers=exc.headers,
        )
