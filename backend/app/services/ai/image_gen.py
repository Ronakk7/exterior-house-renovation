"""Nano Banana image editing interface using Gemini GenerateContent."""

import logging
import time
from dataclasses import dataclass

from google.genai import types

from app.core.config import Settings
from app.core.errors import AIError
from app.services.ai.image_prep import (
    WorkingImage,
    validate_generated_image,
)
from app.services.ai.provider import (
    CallDeadline,
    first_candidate,
    generate_content,
    is_content_blocked,
    log_provider_failure,
    make_ai_error,
)

logger = logging.getLogger(__name__)
_BLOCKED_FINISH_REASONS = {
    "SAFETY",
    "PROHIBITED_CONTENT",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_SAFETY",
    "BLOCKLIST",
    "SPII",
}


@dataclass(frozen=True)
class ImageResult:
    image_bytes: bytes
    mime_type: str
    width_px: int
    height_px: int
    duration_ms: int
    model_name: str
    text_note: str


class ImageClient:
    """Image-generation interface consumed by redesign services."""

    def edit_image(
        self,
        image: WorkingImage,
        instructions: str,
        prompt_version: str,
        timeout_s: float | None = None,
    ) -> ImageResult:
        raise NotImplementedError


class GeminiImageClient(ImageClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def edit_image(
        self,
        image: WorkingImage,
        instructions: str,
        prompt_version: str,
        timeout_s: float | None = None,
    ) -> ImageResult:
        operation = "redesign"
        timeout = (
            timeout_s if timeout_s is not None else self.settings.AI_IMAGE_TIMEOUT_S
        )
        deadline = CallDeadline(timeout)
        started = time.monotonic()
        try:
            response = generate_content(
                self.settings,
                model=self.settings.NANO_BANANA_IMAGE_MODEL,
                operation=operation,
                attempts=1,
                deadline=deadline,
                contents=[
                    instructions,
                    types.Part.from_bytes(
                        data=image.bytes,
                        mime_type=image.mime_type,
                    ),
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(image_size="1K"),
                ),
                image_operation=True,
            )
            if is_content_blocked(response):
                raise make_ai_error(
                    "AI_CONTENT_BLOCKED", operation, 1, image_operation=True
                )
            candidate = first_candidate(response)
            if candidate is None:
                raise make_ai_error(
                    "AI_INVALID_RESPONSE", operation, 1, image_operation=True
                )
            finish_reason = str(
                getattr(candidate, "finish_reason", "")
            ).rsplit(".", 1)[-1].upper()
            if finish_reason in _BLOCKED_FINISH_REASONS:
                raise make_ai_error(
                    "AI_CONTENT_BLOCKED", operation, 1, image_operation=True
                )

            parts = getattr(getattr(candidate, "content", None), "parts", None) or []
            text_parts: list[str] = []
            image_bytes: bytes | None = None
            response_mime_type: str | None = None
            for part in parts:
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    text_parts.append(text)
                inline_data = getattr(part, "inline_data", None)
                mime_type = getattr(inline_data, "mime_type", None)
                data = getattr(inline_data, "data", None)
                if (
                    image_bytes is None
                    and isinstance(mime_type, str)
                    and mime_type.startswith("image/")
                    and isinstance(data, (bytes, bytearray))
                ):
                    image_bytes = bytes(data)
                    response_mime_type = mime_type

            text_note = " ".join(text_parts)[:500]
            if _contains_refusal(text_note):
                raise make_ai_error(
                    "AI_CONTENT_BLOCKED", operation, 1, image_operation=True
                )
            if image_bytes is None:
                raise make_ai_error(
                    "AI_INVALID_RESPONSE", operation, 1, image_operation=True
                )
            try:
                decoded_mime_type, width, height = validate_generated_image(image_bytes)
            except ValueError as exc:
                raise make_ai_error(
                    "AI_INVALID_RESPONSE", operation, 1, image_operation=True
                ) from exc
            if decoded_mime_type != response_mime_type or deadline.remaining() <= 0:
                code = "AI_TIMEOUT" if deadline.remaining() <= 0 else "AI_INVALID_RESPONSE"
                raise make_ai_error(code, operation, 1, image_operation=True)

            duration_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "AI operation succeeded operation=%s model=%s attempts=1 duration_ms=%s",
                operation,
                self.settings.NANO_BANANA_IMAGE_MODEL,
                duration_ms,
            )
            return ImageResult(
                image_bytes=image_bytes,
                mime_type=response_mime_type,
                width_px=width,
                height_px=height,
                duration_ms=duration_ms,
                model_name=self.settings.NANO_BANANA_IMAGE_MODEL,
                text_note=text_note,
            )
        except AIError as exc:
            log_provider_failure(
                operation,
                exc.code,
                exc.__cause__ or exc.code,
                self.settings.GEMINI_API_KEY,
            )
            raise make_ai_error(
                exc.code, operation, 1, image_operation=True
            ) from exc


def _contains_refusal(text: str) -> bool:
    normalized = text.casefold()
    return any(
        phrase in normalized
        for phrase in (
            "i cannot help",
            "i can't help",
            "i cannot assist",
            "i can't assist",
            "i am unable to help",
            "i'm unable to help",
            "i am unable to assist",
            "i'm unable to assist",
        )
    )
