"""Mocked-SDK tests for the shared Gemini Vision and image interfaces."""

import json
import logging
import sys
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from pydantic import BaseModel, ConfigDict
from google.genai import errors, types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings
from app.core.errors import AIError
from app.services.ai import get_image_client, get_vision_client
from app.services.ai.image_gen import GeminiImageClient
from app.services.ai.image_prep import (
    WorkingImage,
    prepare_working_image,
)
from app.services.ai.vision import GeminiVisionClient


class DetectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usable: bool
    quality_reason: str | None
    components: list[object]


def make_image_bytes(
    size: tuple[int, int] = (512, 320), image_format: str = "PNG"
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (120, 150, 180)).save(output, format=image_format)
    return output.getvalue()


def make_working_image(
    image_bytes: bytes | None = None,
    size: tuple[int, int] = (512, 320),
) -> WorkingImage:
    data = image_bytes or make_image_bytes(size, "JPEG")
    with Image.open(BytesIO(data)) as decoded:
        width, height = decoded.size
    return WorkingImage(data, "image/jpeg", width, height, 1.0)


def vision_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_feedback=None,
        candidates=[
            SimpleNamespace(
                finish_reason=types.FinishReason.STOP,
                content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
            )
        ],
    )


def image_response(image_bytes: bytes, text: str = "A redesigned facade") -> SimpleNamespace:
    return SimpleNamespace(
        prompt_feedback=None,
        candidates=[
            SimpleNamespace(
                finish_reason=types.FinishReason.STOP,
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text=text),
                        SimpleNamespace(
                            inline_data=SimpleNamespace(
                                mime_type="image/png",
                                data=image_bytes,
                            )
                        ),
                        SimpleNamespace(
                            inline_data=SimpleNamespace(
                                mime_type="image/png",
                                data=make_image_bytes((300, 300)),
                            )
                        ),
                    ]
                ),
            )
        ],
    )


class FakeSDKClient:
    def __init__(self, responses, calls):
        self.models = SimpleNamespace(
            generate_content=lambda **kwargs: self._generate(kwargs, responses, calls)
        )

    @staticmethod
    def _generate(kwargs, responses, calls):
        calls.append(kwargs)
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class TestImagePreparation(unittest.TestCase):
    def test_downscales_and_removes_exif_metadata(self):
        original = Image.new("RGB", (4000, 3000), (100, 120, 140))
        exif = Image.Exif()
        exif[274] = 1
        source = BytesIO()
        original.save(source, format="JPEG", exif=exif)

        result = prepare_working_image(
            source.getvalue(),
            Settings(_env_file=None, AI_WORKING_IMAGE_MAX_PX=1600),
        )

        self.assertEqual((result.width_px, result.height_px), (1600, 1200))
        self.assertAlmostEqual(result.width_px / result.height_px, 4 / 3)
        self.assertEqual(result.mime_type, "image/jpeg")
        with Image.open(BytesIO(result.bytes)) as decoded:
            self.assertFalse(decoded.getexif())

    def test_applies_exif_orientation_before_scaling(self):
        original = Image.new("RGB", (400, 200), (100, 120, 140))
        exif = Image.Exif()
        exif[274] = 6
        source = BytesIO()
        original.save(source, format="JPEG", exif=exif)

        result = prepare_working_image(
            source.getvalue(),
            Settings(_env_file=None, AI_WORKING_IMAGE_MAX_PX=300),
        )

        self.assertEqual((result.width_px, result.height_px), (150, 300))

    def test_rejects_corrupt_input(self):
        with self.assertRaises(RuntimeError):
            prepare_working_image(
                b"not an image",
                Settings(_env_file=None),
            )


class TestGeminiVisionClient(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            _env_file=None,
            GEMINI_API_KEY="test-key-never-log",
            GEMINI_VISION_MODEL="vision-model-test",
            NANO_BANANA_IMAGE_MODEL="image-model-test",
            AI_MAX_RETRIES=1,
        )
        self.image = make_working_image()
        self.raw_json = json.dumps(
            {"usable": True, "quality_reason": None, "components": []}
        )

    def use_responses(self, responses):
        calls = []
        with patch(
            "app.services.ai.provider.genai.Client",
            side_effect=lambda **kwargs: FakeSDKClient(responses, calls),
        ) as client_factory:
            result = GeminiVisionClient(self.settings).analyze_image(
                self.image,
                "Return a JSON object.",
                DetectionEnvelope,
                "det-v2",
            )
        return result, calls, client_factory

    def test_uses_generate_content_json_and_no_sampling_parameters(self):
        result, calls, client_factory = self.use_responses(
            [vision_response(self.raw_json)]
        )

        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.model_name, "vision-model-test")
        self.assertEqual(result.raw_text_excerpt, self.raw_json)
        self.assertEqual(calls[0]["model"], "vision-model-test")
        self.assertEqual(calls[0]["config"].response_mime_type, "application/json")
        self.assertIsNone(calls[0]["config"].temperature)
        self.assertTrue(hasattr(calls[0]["contents"][0], "inline_data"))
        self.assertEqual(client_factory.call_args.kwargs["api_key"], "test-key-never-log")

    def test_retries_invalid_json_once_with_corrective_suffix(self):
        result, calls, _ = self.use_responses(
            [vision_response("not json"), vision_response(self.raw_json)]
        )

        self.assertEqual(result.attempts, 2)
        self.assertIn("previous reply was not valid JSON", calls[1]["contents"][1])

    def test_retries_invalid_top_level_envelope(self):
        extra_field = json.dumps(
            {
                "usable": True,
                "quality_reason": None,
                "components": [],
                "unexpected": True,
            }
        )
        result, calls, _ = self.use_responses(
            [vision_response(extra_field), vision_response(self.raw_json)]
        )
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(calls), 2)

    def test_retries_provider_5xx_once_but_not_429_or_authentication(self):
        api_5xx = errors.APIError(
            503,
            {"error": {"code": 503, "message": "provider unavailable", "status": "UNAVAILABLE"}},
        )
        result, calls, _ = self.use_responses(
            [api_5xx, vision_response(self.raw_json)]
        )
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(calls), 2)

        for status, expected_code in ((429, "AI_RATE_LIMITED"), (403, "AI_UPSTREAM_ERROR")):
            with self.subTest(status=status):
                failure = errors.APIError(
                    status,
                    {"error": {"code": status, "message": "provider rejected request"}},
                )
                calls = []
                with patch(
                    "app.services.ai.provider.genai.Client",
                    side_effect=lambda **kwargs: FakeSDKClient([failure], calls),
                ):
                    with self.assertRaises(AIError) as raised:
                        GeminiVisionClient(self.settings).analyze_image(
                            self.image,
                            "Return a JSON object.",
                            DetectionEnvelope,
                            "det-v2",
                        )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(raised.exception.details["attempts"], 1)
                self.assertEqual(len(calls), 1)

    def test_provider_error_logs_are_bounded_and_do_not_leak_api_key(self):
        secret = self.settings.GEMINI_API_KEY
        failure = errors.APIError(
            503,
            {
                "error": {
                    "code": 503,
                    "message": f"provider failed with {secret}",
                    "status": "UNAVAILABLE",
                }
            },
        )
        calls = []
        with patch(
            "app.services.ai.provider.genai.Client",
            side_effect=lambda **kwargs: FakeSDKClient([failure, failure], calls),
        ):
            with self.assertLogs("app.services.ai", level=logging.WARNING) as logs:
                with self.assertRaises(AIError):
                    GeminiVisionClient(self.settings).analyze_image(
                        self.image,
                        "Return a JSON object.",
                        DetectionEnvelope,
                        "det-v2",
                    )
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_timeout_after_sdk_response_is_reported(self):
        slow_response = vision_response(self.raw_json)
        calls = []

        def delayed_response(**kwargs):
            time.sleep(0.03)
            return FakeSDKClient([slow_response], calls).models.generate_content(**kwargs)

        with patch(
            "app.services.ai.provider.genai.Client",
            return_value=SimpleNamespace(
                models=SimpleNamespace(generate_content=delayed_response)
            ),
        ):
            with self.assertRaises(AIError) as raised:
                GeminiVisionClient(self.settings).analyze_image(
                    self.image,
                    "Return a JSON object.",
                    DetectionEnvelope,
                    "det-v2",
                    timeout_s=0.01,
                )
        self.assertEqual(raised.exception.code, "AI_TIMEOUT")


class TestGeminiImageClient(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            _env_file=None,
            GEMINI_API_KEY="test-key-never-log",
            GEMINI_VISION_MODEL="vision-model-test",
            NANO_BANANA_IMAGE_MODEL="image-model-test",
        )
        self.image = make_working_image()
        self.generated = make_image_bytes((512, 320))

    def test_requests_text_and_image_at_1k_and_parses_first_image(self):
        calls = []
        response = image_response(self.generated, "Generated facade")
        with patch(
            "app.services.ai.provider.genai.Client",
            side_effect=lambda **kwargs: FakeSDKClient([response], calls),
        ):
            result = GeminiImageClient(self.settings).edit_image(
                self.image,
                "Apply the requested redesign.",
                "redesign-v1",
            )

        self.assertEqual(result.image_bytes, self.generated)
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual((result.width_px, result.height_px), (512, 320))
        self.assertEqual(result.text_note, "Generated facade")
        self.assertEqual(calls[0]["model"], "image-model-test")
        config = calls[0]["config"]
        self.assertEqual(config.response_modalities, ["TEXT", "IMAGE"])
        self.assertEqual(config.image_config.image_size, "1K")

    def test_image_api_failure_is_not_retried(self):
        failure = errors.APIError(
            503,
            {"error": {"code": 503, "message": "provider unavailable", "status": "UNAVAILABLE"}},
        )
        calls = []
        with patch(
            "app.services.ai.provider.genai.Client",
            side_effect=lambda **kwargs: FakeSDKClient([failure], calls),
        ):
            with self.assertRaises(AIError) as raised:
                GeminiImageClient(self.settings).edit_image(
                    self.image, "Apply the requested redesign.", "redesign-v1"
                )
        self.assertEqual(raised.exception.code, "AI_UPSTREAM_ERROR")
        self.assertEqual(raised.exception.details["attempts"], 1)
        self.assertEqual(len(calls), 1)

    def test_rejects_refusal_and_invalid_image_output(self):
        blocked = image_response(self.generated, "I cannot help with that request.")
        invalid = image_response(b"not an image")
        for response, code in (
            (blocked, "AI_CONTENT_BLOCKED"),
            (invalid, "AI_INVALID_RESPONSE"),
        ):
            calls = []
            with self.subTest(code=code), patch(
                "app.services.ai.provider.genai.Client",
                side_effect=lambda **kwargs: FakeSDKClient([response], calls),
            ):
                with self.assertRaises(AIError) as raised:
                    GeminiImageClient(self.settings).edit_image(
                        self.image, "Apply the requested redesign.", "redesign-v1"
                    )
                self.assertEqual(raised.exception.code, code)


class TestMockClients(unittest.TestCase):
    def test_mock_factories_work_without_api_key_for_both_capabilities(self):
        settings = Settings(_env_file=None, AI_MOCK_MODE=True)
        working = make_working_image()
        with (
            patch("app.services.ai.mock.time.sleep"),
        ):
            vision = get_vision_client(settings).analyze_image(
                working,
                "Return a detection envelope.",
                DetectionEnvelope,
                "det-v2",
            )
            image = get_image_client(settings).edit_image(
                working,
                "Apply a redesign.",
                "redesign-v1",
            )

        self.assertTrue(vision.data.usable)
        self.assertEqual(len(vision.data.components), 11)
        self.assertIn("DEMO", image.text_note)
        self.assertGreaterEqual(image.width_px, 256)
        self.assertGreaterEqual(image.height_px, 256)

    def test_mock_vision_scenarios_and_shared_errors(self):
        working = make_working_image()
        for scenario, usable, count in (
            ("unusable", False, 0),
            ("no_components", True, 0),
        ):
            settings = Settings(
                _env_file=None,
                AI_MOCK_MODE=True,
                AI_MOCK_SCENARIO=scenario,
            )
            with patch("app.services.ai.mock.time.sleep"):
                result = get_vision_client(settings).analyze_image(
                    working, "", DetectionEnvelope, "det-v2"
                )
            self.assertEqual(result.data.usable, usable)
            self.assertEqual(len(result.data.components), count)

        for scenario, code in (
            ("invalid_json", "AI_INVALID_RESPONSE"),
            ("blocked", "AI_CONTENT_BLOCKED"),
            ("timeout", "AI_TIMEOUT"),
            ("rate_limited", "AI_RATE_LIMITED"),
        ):
            settings = Settings(
                _env_file=None,
                AI_MOCK_MODE=True,
                AI_MOCK_SCENARIO=scenario,
            )
            with patch("app.services.ai.mock.time.sleep"):
                with self.assertRaises(AIError) as raised:
                    get_vision_client(settings).analyze_image(
                        working, "", DetectionEnvelope, "det-v2"
                    )
            self.assertEqual(raised.exception.code, code)

    def test_unconfigured_factories_raise_ai_not_configured(self):
        settings = Settings(_env_file=None)
        with self.assertRaises(AIError) as vision_error:
            get_vision_client(settings).analyze_image(
                make_working_image(), "", DetectionEnvelope, "det-v2"
            )
        with self.assertRaises(AIError) as image_error:
            get_image_client(settings).edit_image(
                make_working_image(), "", "redesign-v1"
            )
        self.assertEqual(vision_error.exception.code, "AI_NOT_CONFIGURED")
        self.assertEqual(image_error.exception.code, "AI_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
