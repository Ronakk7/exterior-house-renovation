"""Application exception hierarchy matching specification error codes."""

from typing import Any, Dict, Optional


class AppError(Exception):
    """Base application exception."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


class ValidationAppError(AppError):
    """Request validation error (422)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            http_status=422,
            details=details,
        )


class NotFoundError(AppError):
    """Resource not found error (404)."""

    def __init__(self, resource: str, message: Optional[str] = None) -> None:
        super().__init__(
            code="NOT_FOUND",
            message=message or f"{resource.capitalize()} not found.",
            http_status=404,
            details={"resource": resource},
        )


class ConflictError(AppError):
    """State or uniqueness conflict error (409)."""

    def __init__(
        self,
        code: str = "CONFLICT",
        message: str = "A conflict occurred with current resource state.",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            http_status=409,
            details=details,
        )


class UploadError(AppError):
    """File upload validation errors (413, 415, 422)."""

    STATUS_MAP = {
        "UPLOAD_INVALID_TYPE": 415,
        "UPLOAD_TOO_LARGE": 413,
        "UPLOAD_TOO_SMALL": 422,
        "UPLOAD_CORRUPT": 422,
    }

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        http_status = self.STATUS_MAP.get(code, 422)
        super().__init__(
            code=code,
            message=message,
            http_status=http_status,
            details=details,
        )


class CatalogueError(AppError):
    """Catalogue incompatibility error (422)."""

    def __init__(
        self,
        message: str = "Material is unknown or not compatible with component type.",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            code="MATERIAL_INCOMPATIBLE",
            message=message,
            http_status=422,
            details=details,
        )


class AIError(AppError):
    """AI provider failure mapping (422, 429, 502, 503, 504)."""

    STATUS_MAP = {
        "AI_NOT_CONFIGURED": 503,
        "AI_TIMEOUT": 504,
        "AI_RATE_LIMITED": 429,
        "AI_UPSTREAM_ERROR": 502,
        "AI_INVALID_RESPONSE": 502,
        "AI_CONTENT_BLOCKED": 422,
    }

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        http_status = self.STATUS_MAP.get(code, 502)
        super().__init__(
            code=code,
            message=message,
            http_status=http_status,
            details=details,
        )

