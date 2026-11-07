"""Gemini Vision GenerateContent interface with bounded retry behavior."""

import logging
import time
from dataclasses import dataclass
from typing import Any, Type

from google.genai import types
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AIError
from app.services.ai.image_prep import WorkingImage
from app.services.ai.json_validation import InvalidModelJSON, parse_and_validate
from app.services.ai.provider import (
    RETRY_MIN_REMAINING_S,
    CallDeadline,
    first_candidate,
    generate_content,
    is_content_blocked,
    log_provider_failure,
    make_ai_error,
)

logger = logging.getLogger(__name__)
_CORRECTIVE_SUFFIX = (
    "Your previous reply was not valid JSON matching the required schema. "
    "Reply again with only the JSON object."
)
_BLOCKED_FINISH_REASONS = {
    "SAFETY",
    "PROHIBITED_CONTENT",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_SAFETY",
    "BLOCKLIST",
    "SPII",
}


@dataclass(frozen=True)
class VisionResult:
    data: Any
    attempts: int
    duration_ms: int
    model_name: str
    raw_text_excerpt: str


class VisionClient:
    """Vision interface consumed by feature services."""

    def analyze_image(
        self,
        image: WorkingImage,
        instructions: str,
        schema: Type[BaseModel],
        prompt_version: str,
        timeout_s: float | None = None,
    ) -> VisionResult:
        raise NotImplementedError


class GeminiVisionClient(VisionClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze_image(
        self,
        image: WorkingImage,
        instructions: str,
        schema: Type[BaseModel],
        prompt_version: str,
        timeout_s: float | None = None,
    ) -> VisionResult:
        timeout = (
            timeout_s
            if timeout_s is not None
            else self.settings.AI_DETECTION_TIMEOUT_S
        )
        deadline = CallDeadline(timeout)
        started = time.monotonic()
        attempts_allowed = min(1, self.settings.AI_MAX_RETRIES)
        operation = "ai_estimate" if prompt_version.startswith("estimate") else "detection"
        last_error: AIError | None = None
        raw_text = ""

        for attempt in range(1, attempts_allowed + 2):
            current_instructions = instructions
            if attempt > 1:
                current_instructions = f"{instructions}\n\n{_CORRECTIVE_SUFFIX}"
            try:
                response = generate_content(
                    self.settings,
                    model=self.settings.GEMINI_VISION_MODEL,
                    operation=operation,
                    attempts=attempt,
                    deadline=deadline,
                    contents=[
                        types.Part.from_bytes(
                            data=image.bytes,
                            mime_type=image.mime_type,
                        ),
                        current_instructions,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                if is_content_blocked(response):
                    raise make_ai_error("AI_CONTENT_BLOCKED", operation, attempt)

                candidate = first_candidate(response)
                if candidate is None:
                    raise make_ai_error("AI_INVALID_RESPONSE", operation, attempt)
                finish_reason = str(
                    getattr(candidate, "finish_reason", "")
                ).rsplit(".", 1)[-1].upper()
                if finish_reason in _BLOCKED_FINISH_REASONS:
                    raise make_ai_error("AI_CONTENT_BLOCKED", operation, attempt)
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) or []
                raw_text = "".join(
                    part.text for part in parts if isinstance(getattr(part, "text", None), str)
                )
                if not raw_text:
                    raise make_ai_error("AI_INVALID_RESPONSE", operation, attempt)
                parsed = parse_and_validate(raw_text, schema)
                if deadline.remaining() <= 0:
                    raise make_ai_error("AI_TIMEOUT", operation, attempt)

                duration_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "AI operation succeeded operation=%s model=%s attempts=%s "
                    "duration_ms=%s",
                    operation,
                    self.settings.GEMINI_VISION_MODEL,
                    attempt,
                    duration_ms,
                )
                return VisionResult(
                    data=parsed,
                    attempts=attempt,
                    duration_ms=duration_ms,
                    model_name=self.settings.GEMINI_VISION_MODEL,
                    raw_text_excerpt=raw_text[:1000],
                )
            except InvalidModelJSON as exc:
                last_error = make_ai_error("AI_INVALID_RESPONSE", operation, attempt)
                failure_detail: Any = exc
            except AIError as exc:
                last_error = exc
                failure_detail = exc.__cause__ or exc.code

            can_retry = (
                attempt <= attempts_allowed
                and (
                    last_error.code == "AI_INVALID_RESPONSE"
                    or (
                        last_error.code == "AI_UPSTREAM_ERROR"
                        and getattr(last_error, "retryable", False)
                    )
                )
                and deadline.remaining() >= RETRY_MIN_REMAINING_S
            )
            if can_retry:
                logger.warning(
                    "Retrying AI operation operation=%s attempt=%s reason=%s",
                    operation,
                    attempt,
                    last_error.code,
                )
                continue

            final_error = make_ai_error(
                last_error.code,
                operation,
                attempt,
                image_operation=False,
            )
            log_provider_failure(
                operation,
                last_error.code,
                failure_detail,
                self.settings.GEMINI_API_KEY,
            )
            raise final_error from last_error

        raise make_ai_error(
            "AI_INVALID_RESPONSE", operation, attempts_allowed + 1
        )
