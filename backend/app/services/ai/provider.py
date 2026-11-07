"""Shared Google GenAI SDK calls, concurrency control, deadlines, and error mapping."""

import logging
import re
import threading
import time
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.core.config import Settings
from app.core.errors import AIError

MAX_CONCURRENT_AI_CALLS = 4
RETRY_MIN_REMAINING_S = 15
_CALL_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_AI_CALLS)
logger = logging.getLogger(__name__)

_MESSAGES = {
    "AI_NOT_CONFIGURED": "AI features are not set up on this server yet.",
    "AI_TIMEOUT": "The AI service took too long to respond. Please try again.",
    "AI_RATE_LIMITED": (
        "The AI service is busy or its usage limit was reached. "
        "Please wait a minute and try again."
    ),
    "AI_UPSTREAM_ERROR": "The AI service is temporarily unavailable. Please try again.",
    "AI_INVALID_RESPONSE": "The AI returned an answer we could not use. Please try again.",
    "AI_CONTENT_BLOCKED": "The AI service declined to analyse this photo. Try a different photo.",
}
_IMAGE_MESSAGES = {
    **_MESSAGES,
    "AI_INVALID_RESPONSE": "The AI did not return a usable image. Please try again.",
    "AI_CONTENT_BLOCKED": (
        "The AI service declined to generate this design. "
        "Try different materials or a different photo."
    ),
}


class CallDeadline:
    """Track one end-to-end operation deadline."""

    def __init__(self, timeout_s: float) -> None:
        self.ends_at = time.monotonic() + timeout_s

    def remaining(self) -> float:
        return max(0.0, self.ends_at - time.monotonic())


class ProviderAIError(AIError):
    """AI error annotated with whether a Vision retry is permitted."""

    def __init__(self, code: str, operation: str, attempts: int, retryable: bool):
        super().__init__(
            code,
            _MESSAGES[code],
            details={"operation": operation, "attempts": attempts},
        )
        self.retryable = retryable


def make_ai_error(
    code: str, operation: str, attempts: int, *, image_operation: bool = False
) -> AIError:
    """Build an AI error with only the documented details."""
    messages = _IMAGE_MESSAGES if image_operation else _MESSAGES
    return AIError(
        code,
        messages[code],
        details={"operation": operation, "attempts": attempts},
    )


def generate_content(
    settings: Settings,
    *,
    model: str,
    operation: str,
    attempts: int,
    deadline: CallDeadline,
    contents: list[Any],
    config: types.GenerateContentConfig,
    image_operation: bool = False,
) -> Any:
    """Call the single supported SDK GenerateContent API under the shared cap."""
    remaining = deadline.remaining()
    if remaining <= 0 or not _CALL_SLOTS.acquire(timeout=remaining):
        raise make_ai_error(
            "AI_TIMEOUT", operation, attempts, image_operation=image_operation
        )

    try:
        remaining = deadline.remaining()
        if remaining <= 0:
            raise make_ai_error(
                "AI_TIMEOUT", operation, attempts, image_operation=image_operation
            )
        client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=max(1, int(remaining * 1000))),
        )
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except errors.APIError as exc:
            code = _api_error_code(exc)
            provider_status = exc.code if isinstance(exc.code, int) else 0
            if code == "AI_UPSTREAM_ERROR" and provider_status in (401, 403):
                logger.error(
                    "AI provider authentication or permission failure "
                    "operation=%s provider_status=%s",
                    operation,
                    provider_status,
                )
            raise ProviderAIError(
                code,
                operation,
                attempts,
                retryable=code == "AI_UPSTREAM_ERROR" and provider_status >= 500,
            ) from exc
        except (httpx.TimeoutException, TimeoutError, OSError) as exc:
            code = "AI_TIMEOUT" if isinstance(
                exc, (httpx.TimeoutException, TimeoutError)
            ) else "AI_UPSTREAM_ERROR"
            raise ProviderAIError(
                code,
                operation,
                attempts,
                retryable=code == "AI_UPSTREAM_ERROR",
            ) from exc

        if deadline.remaining() <= 0:
            raise make_ai_error(
                "AI_TIMEOUT", operation, attempts, image_operation=image_operation
            )
        return response
    finally:
        _CALL_SLOTS.release()


def _api_error_code(exc: errors.APIError) -> str:
    status = exc.code if isinstance(exc.code, int) else 0
    if status == 429:
        return "AI_RATE_LIMITED"
    if status in (401, 403) or status >= 500:
        return "AI_UPSTREAM_ERROR"
    if status == 408:
        return "AI_TIMEOUT"
    return "AI_UPSTREAM_ERROR"


def safe_provider_detail(value: Any, api_key: str) -> str:
    """Bound provider detail and remove credentials before it reaches logs."""
    detail = str(value).replace(api_key, "[REDACTED]") if api_key else str(value)
    detail = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", detail)
    return detail[:300]


def log_provider_failure(
    operation: str, code: str, detail: Any, api_key: str
) -> None:
    """Log bounded provider diagnostics without response payloads or credentials."""
    logger.error(
        "AI operation failed operation=%s code=%s provider_detail=%s",
        operation,
        code,
        safe_provider_detail(detail, api_key),
    )


def enum_name(value: Any) -> str:
    """Normalize SDK enum or string values."""
    return str(getattr(value, "name", value)).rsplit(".", 1)[-1].upper()


def is_content_blocked(response: Any) -> bool:
    """Check prompt feedback and candidate finish reasons before reading content."""
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None)
    if block_reason and enum_name(block_reason) not in {
        "BLOCK_REASON_UNSPECIFIED",
        "UNSPECIFIED",
        "NONE",
    }:
        return True

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return False
    finish_reason = getattr(candidates[0], "finish_reason", None)
    return enum_name(finish_reason) in {
        "SAFETY",
        "PROHIBITED_CONTENT",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_SAFETY",
        "BLOCKLIST",
        "SPII",
    }


def first_candidate(response: Any) -> Any | None:
    candidates = getattr(response, "candidates", None) or []
    return candidates[0] if candidates else None
