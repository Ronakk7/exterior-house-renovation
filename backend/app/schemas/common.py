"""Common validators and models used across schema definitions."""

from typing import Any, Dict, List
from pydantic import BaseModel, ConfigDict, Field, model_validator

COMPONENT_TYPES: List[str] = [
    "wall",
    "window",
    "door",
    "balcony",
    "railing",
    "pillar",
    "parapet",
    "gate",
    "roof_edge",
    "other",
]

PROJECT_STEPS: List[str] = [
    "upload",
    "components",
    "materials",
    "redesign",
    "estimate",
    "report",
]


class Box(BaseModel):
    """Normalized bounding box with coordinates in [0, 1]."""

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., gt=0.0, le=1.0)
    h: float = Field(..., gt=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_bounds(self) -> "Box":
        # Check that box fits within [0, 1] with a tiny tolerance for float rounding
        if (self.x + self.w) > 1.002:
            raise ValueError(f"Box right edge ({self.x + self.w}) exceeds 1.0")
        if (self.y + self.h) > 1.002:
            raise ValueError(f"Box bottom edge ({self.y + self.h}) exceeds 1.0")
        return self


class ErrorDetail(BaseModel):
    """Standard error response payload."""

    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    request_id: str


class StandardErrorResponse(BaseModel):
    """Root wrapper for all API error responses."""

    error: ErrorDetail

