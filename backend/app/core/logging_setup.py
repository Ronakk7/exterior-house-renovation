"""Structured logging, request ID, timing, and security headers middleware."""

import logging
import re
import time
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.ids import generate_request_id

logger = logging.getLogger("app.access")

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="req_none")
_REQUEST_ID_REGEX = re.compile(r"^req_[0-9a-f]{12}$")
_PROJECT_ID_REGEX = re.compile(r"prj_[0-9a-f]{16}")


def get_request_id() -> str:
    """Return the request ID from the current context."""
    return _request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    """Log filter that injects the current request_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger with unified single-line format."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]


class RequestLoggingAndSecurityMiddleware(BaseHTTPMiddleware):
    """Middleware handling request IDs, security headers, and single-line access logs."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 1. Request ID assignment
        client_req_id = request.headers.get("X-Request-ID")
        if client_req_id and _REQUEST_ID_REGEX.match(client_req_id):
            req_id = client_req_id
        else:
            req_id = generate_request_id()

        token = _request_id_ctx.set(req_id)
        start_time = time.perf_counter()

        try:
            response = await call_next(request)

            # 2. Security & Tracing Headers
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"

            # 3. Access Logging per spec 04 §9
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            path = request.url.path
            proj_match = _PROJECT_ID_REGEX.search(path)
            proj_str = f" project_id={proj_match.group()}" if proj_match else ""

            logger.info(
                f"method={request.method} path={path} status={response.status_code} "
                f"duration_ms={duration_ms}{proj_str}"
            )
            return response
        finally:
            _request_id_ctx.reset(token)
