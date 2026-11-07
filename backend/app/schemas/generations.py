"""AI redesign generation schemas."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class GenerationCreate(BaseModel):
    """Payload to trigger an exterior redesign."""

    photo_id: Optional[str] = None
    extra_instructions: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class GenerationApproval(BaseModel):
    """Payload to set variant approval status."""

    is_approved: bool

    model_config = ConfigDict(extra="forbid")


class GenerationResponse(BaseModel):
    """Generation overview metadata."""

    id: str
    project_id: str
    variant_id: str
    photo_id: str
    status: str
    is_stale: bool
    is_approved: bool
    extra_instructions: Optional[str] = None
    model_name: str
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    image_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None


class GenerationDetailResponse(GenerationResponse):
    """Full generation detail including prompt text."""

    prompt_text: str


class GenerationListResponse(BaseModel):
    """List of generations for a variant or project."""

    items: List[GenerationResponse]

