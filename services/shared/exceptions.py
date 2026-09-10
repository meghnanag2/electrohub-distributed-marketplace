import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

log = structlog.get_logger()


class ElectroHubException(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class AuthException(ElectroHubException):
    status_code = 401
    error_code = "AUTH_ERROR"


class InvalidCredentialsException(AuthException):
    error_code = "INVALID_CREDENTIALS"


class TokenExpiredException(AuthException):
    error_code = "TOKEN_EXPIRED"


class TokenMissingException(AuthException):
    error_code = "TOKEN_MISSING"


class ForbiddenException(ElectroHubException):
    status_code = 403
    error_code = "FORBIDDEN"


class NotFoundException(ElectroHubException):
    status_code = 404
    error_code = "NOT_FOUND"


class ItemNotFoundException(NotFoundException):
    error_code = "ITEM_NOT_FOUND"


class UserNotFoundException(NotFoundException):
    error_code = "USER_NOT_FOUND"


class ConflictException(ElectroHubException):
    status_code = 409
    error_code = "CONFLICT"


class ValidationException(ElectroHubException):
    status_code = 422
    error_code = "VALIDATION_ERROR"


class RateLimitException(ElectroHubException):
    status_code = 429
    error_code = "RATE_LIMITED"

    def __init__(self, message: str, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(message)


class ServiceException(ElectroHubException):
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"


class DatabaseException(ServiceException):
    error_code = "DATABASE_ERROR"


class CacheException(ServiceException):
    error_code = "CACHE_ERROR"


class EmailServiceException(ServiceException):
    error_code = "EMAIL_SERVICE_ERROR"


class GrpcServiceException(ServiceException):
    error_code = "GRPC_SERVICE_ERROR"


async def electrohub_exception_handler(request: Request, exc: ElectroHubException):
    extra = {"retry_after": exc.retry_after} if isinstance(exc, RateLimitException) else {}
    log.warning("app_exception", error_code=exc.error_code, message=exc.message,
                path=request.url.path, **extra)
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimitException) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error_code, "message": exc.message},
        headers=headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", exc_type=type(exc).__name__,
              message=str(exc), path=request.url.path, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
    )
