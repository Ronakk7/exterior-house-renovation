"""Factories for the independent Gemini Vision and image-generation clients."""

from app.core.config import Settings
from app.services.ai.image_gen import GeminiImageClient, ImageClient
from app.services.ai.mock import MockImageClient, MockVisionClient
from app.services.ai.vision import GeminiVisionClient, VisionClient
from app.services.ai.provider import make_ai_error


class UnconfiguredVisionClient(VisionClient):
    """Fail closed when live provider configuration is incomplete."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze_image(self, *args, **kwargs):
        raise make_ai_error("AI_NOT_CONFIGURED", "detection", 1)


class UnconfiguredImageClient(ImageClient):
    """Fail closed when live provider configuration is incomplete."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def edit_image(self, *args, **kwargs):
        raise make_ai_error("AI_NOT_CONFIGURED", "redesign", 1)


def get_vision_client(settings: Settings) -> VisionClient:
    """Build the Vision interface without making a provider request."""
    if settings.AI_MOCK_MODE:
        return MockVisionClient(settings)
    if not settings.ai_configured:
        return UnconfiguredVisionClient(settings)
    return GeminiVisionClient(settings)


def get_image_client(settings: Settings) -> ImageClient:
    """Build the image-generation interface without making a provider request."""
    if settings.AI_MOCK_MODE:
        return MockImageClient(settings)
    if not settings.ai_configured:
        return UnconfiguredImageClient(settings)
    return GeminiImageClient(settings)


__all__ = ["get_image_client", "get_vision_client"]
