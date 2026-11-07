"""Strict detection envelope and response schemas."""

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from app.schemas.components import ComponentResponse
from app.schemas.photos import PhotoResponse


class DetectionEnvelope(BaseModel):
    """Top-level model response; individual component entries are validated later."""

    model_config = ConfigDict(extra="forbid", strict=True)

    usable: StrictBool
    quality_reason: Optional[StrictStr]
    components: List[Any]


class DetectionResponse(BaseModel):
    """Result of a synchronous detection run."""

    stage_run_id: str
    photo: PhotoResponse
    usable: bool
    quality_reason: Optional[str] = None
    components: List[ComponentResponse]
    kept_locked_count: int
    warnings: List[str]
