"""System and client configuration response schemas."""

from typing import List
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness and system health report."""

    status: str
    version: str
    database: str
    ai_mock_mode: bool
    ai_configured: bool


class ComponentTypeInfo(BaseModel):
    """Vocabulary item for detected/created building components."""

    type: str
    label: str
    supported: bool


class UploadConfig(BaseModel):
    """Upload constraints sent to client."""

    max_upload_mb: int
    allowed_mime_types: List[str]
    min_short_side_px: int
    max_photos_per_project: int


class LimitsConfig(BaseModel):
    """Input length limits sent to client."""

    extra_instructions_max_chars: int
    project_name_max_chars: int
    max_components_per_photo: int


class ClientConfigResponse(BaseModel):
    """Frontend bootstrapping configuration payload."""

    app_name: str
    currency: str
    currency_symbol: str
    upload: UploadConfig
    component_types: List[ComponentTypeInfo]
    limits: LimitsConfig
    ai_mock_mode: bool
