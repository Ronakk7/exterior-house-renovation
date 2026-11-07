"""Deterministic, local-only mock implementations of both AI interfaces."""

import time
import json
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Type

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AIError
from app.services.ai.image_gen import ImageClient, ImageResult
from app.services.ai.image_prep import WorkingImage, validate_generated_image
from app.services.ai.json_validation import parse_and_validate
from app.services.ai.provider import make_ai_error
from app.services.ai.vision import VisionClient, VisionResult

_MOCK_COMPONENTS = [
    {"type": "wall", "label": "main front wall", "box_2d": [180, 120, 860, 880], "confidence": 0.96},
    {"type": "window", "label": "left ground floor window", "box_2d": [480, 200, 620, 360], "confidence": 0.93},
    {"type": "window", "label": "right ground floor window", "box_2d": [480, 640, 620, 800], "confidence": 0.92},
    {"type": "door", "label": "main entrance door", "box_2d": [570, 430, 850, 570], "confidence": 0.91},
    {"type": "balcony", "label": "first floor balcony", "box_2d": [300, 360, 470, 650], "confidence": 0.88},
    {"type": "railing", "label": "balcony front railing", "box_2d": [420, 350, 470, 660], "confidence": 0.86},
    {"type": "pillar", "label": "left entrance pillar", "box_2d": [520, 390, 870, 430], "confidence": 0.84},
    {"type": "pillar", "label": "right entrance pillar", "box_2d": [520, 570, 870, 610], "confidence": 0.83},
    {"type": "roof_edge", "label": "front roof edge", "box_2d": [120, 100, 210, 900], "confidence": 0.89},
    {"type": "gate", "label": "front compound gate", "box_2d": [800, 100, 980, 900], "confidence": 0.78},
    {"type": "other", "label": "foreground garden area", "box_2d": [870, 100, 990, 900], "confidence": 0.65},
]
_MOCK_ESTIMATES = {
    "wall": {"width_ft": 20.0, "height_ft": 10.0, "area_sqft": 200.0},
    "window": {"width_ft": 4.0, "height_ft": 4.0, "area_sqft": 16.0},
    "door": {"width_ft": 3.0, "height_ft": 7.0, "area_sqft": 21.0},
    "balcony": {"width_ft": 10.0, "height_ft": 4.0, "area_sqft": 40.0},
    "railing": {"length_ft": 10.0},
    "pillar": {"width_ft": 1.0, "height_ft": 10.0, "area_sqft": 10.0},
    "parapet": {"width_ft": 20.0, "height_ft": 3.0, "area_sqft": 60.0},
    "gate": {"width_ft": 8.0, "height_ft": 6.0, "area_sqft": 48.0},
    "roof_edge": {"width_ft": 20.0, "height_ft": 1.0, "area_sqft": 20.0},
}
logger = logging.getLogger(__name__)


class MockVisionClient(VisionClient):
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
        started = time.monotonic()
        time.sleep(1)
        scenario = self.settings.AI_MOCK_SCENARIO
        operation = "ai_estimate" if prompt_version.startswith(("estimate", "est-")) else "detection"
        if scenario in {"blocked", "timeout", "rate_limited"}:
            code = {
                "blocked": "AI_CONTENT_BLOCKED",
                "timeout": "AI_TIMEOUT",
                "rate_limited": "AI_RATE_LIMITED",
            }[scenario]
            raise make_ai_error(code, operation, 1)
        if scenario == "invalid_json":
            logger.warning(
                "Retrying AI operation operation=%s attempt=1 reason=AI_INVALID_RESPONSE",
                operation,
            )
            raise make_ai_error(
                "AI_INVALID_RESPONSE",
                operation,
                min(2, self.settings.AI_MAX_RETRIES + 1),
            )

        if operation == "ai_estimate":
            target_text = instructions.split("ESTIMATE ONLY:", 1)[-1]
            targets = re.findall(r"\b(c\d+)\s*\(([a-z_]+)\)", target_text)
            estimates = []
            for component_ref, component_type in targets:
                estimate = _MOCK_ESTIMATES.get(component_type)
                if estimate is None:
                    continue
                if component_type == "railing":
                    estimates.append(
                        {
                            "component_ref": component_ref,
                            "input_mode": "length",
                            "width_ft": None,
                            "height_ft": None,
                            "length_ft": estimate["length_ft"],
                            "deduction_sqft": None,
                            "uncertainty_pct": 35,
                            "note": "Estimated from the visible railing span.",
                        }
                    )
                else:
                    estimates.append(
                        {
                            "component_ref": component_ref,
                            "input_mode": "dimensions",
                            "width_ft": estimate["width_ft"],
                            "height_ft": estimate["height_ft"],
                            "length_ft": None,
                            "deduction_sqft": 0,
                            "uncertainty_pct": 35,
                            "note": "Estimated using typical exterior dimensions.",
                        }
                    )
            payload: dict[str, Any] = {"estimates": estimates}
        elif scenario == "unusable":
            payload = {
                "usable": False,
                "quality_reason": "The photo is difficult to assess. Try a clearer, brighter view.",
                "components": [],
            }
        elif scenario == "no_components":
            payload = {
                "usable": True,
                "quality_reason": None,
                "components": [],
            }
        else:
            payload = {
                "usable": True,
                "quality_reason": None,
                "components": _MOCK_COMPONENTS,
            }

        validated = parse_and_validate(_encode_json(payload), schema)
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "AI operation succeeded operation=%s model=%s attempts=1 duration_ms=%s",
            operation,
            self.settings.GEMINI_VISION_MODEL or "mock-vision",
            duration_ms,
        )
        return VisionResult(
            data=validated,
            attempts=1,
            duration_ms=duration_ms,
            model_name=self.settings.GEMINI_VISION_MODEL or "mock-vision",
            raw_text_excerpt=_encode_json(payload)[:1000],
        )


class MockImageClient(ImageClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def edit_image(
        self,
        image: WorkingImage,
        instructions: str,
        prompt_version: str,
        timeout_s: float | None = None,
    ) -> ImageResult:
        started = time.monotonic()
        time.sleep(3)
        scenario = self.settings.AI_MOCK_SCENARIO
        if scenario in {"blocked", "timeout", "rate_limited"}:
            code = {
                "blocked": "AI_CONTENT_BLOCKED",
                "timeout": "AI_TIMEOUT",
                "rate_limited": "AI_RATE_LIMITED",
            }[scenario]
            raise make_ai_error(code, "redesign", 1, image_operation=True)

        with Image.open(BytesIO(image.bytes)) as source:
            output = source.convert("RGB")
        tint = Image.new("RGB", output.size, (85, 115, 145))
        output = Image.blend(output, tint, 0.15)
        draw = ImageDraw.Draw(output)
        banner_height = max(42, output.height // 12)
        draw.rectangle((0, 0, output.width, banner_height), fill=(20, 35, 55))
        draw.text(
            (12, max(8, banner_height // 4)),
            "DEMO - simulated redesign",
            fill=(255, 255, 255),
            font=ImageFont.load_default(),
        )
        encoded = BytesIO()
        output.save(encoded, format="JPEG", quality=90)
        image_bytes = encoded.getvalue()
        mime_type, width, height = validate_generated_image(image_bytes)
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "AI operation succeeded operation=redesign model=%s attempts=1 "
            "duration_ms=%s",
            self.settings.NANO_BANANA_IMAGE_MODEL or "mock-image",
            duration_ms,
        )
        return ImageResult(
            image_bytes=image_bytes,
            mime_type=mime_type,
            width_px=width,
            height_px=height,
            duration_ms=duration_ms,
            model_name=self.settings.NANO_BANANA_IMAGE_MODEL or "mock-image",
            text_note="DEMO - simulated redesign",
        )


def _encode_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
