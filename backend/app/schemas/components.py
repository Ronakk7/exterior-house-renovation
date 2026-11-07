"""Building component schemas."""

from typing import List, Optional
import re
import unicodedata
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.common import COMPONENT_TYPES, Box


class ComponentCreate(BaseModel):
    """Payload to create a new component manually."""

    photo_id: str
    type: str
    label: Optional[str] = Field(None, max_length=120)
    box: Box

    model_config = ConfigDict(extra="forbid")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in COMPONENT_TYPES:
            raise ValueError(f"Unknown component type: {v}")
        return v

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Label must be text.")
        cleaned = _clean_label(value)
        return cleaned or None


class ComponentUpdate(BaseModel):
    """Payload to modify an existing component."""

    type: Optional[str] = None
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    box: Optional[Box] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in COMPONENT_TYPES:
            raise ValueError(f"Unknown component type: {v}")
        return v

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Label must be text.")
        cleaned = _clean_label(value)
        if not cleaned:
            raise ValueError("Label must contain 1-120 characters.")
        return cleaned

    @model_validator(mode="after")
    def validate_changes(self) -> "ComponentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one component field is required.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Component fields cannot be null.")
        return self


class ComponentResponse(BaseModel):
    """Component representation."""

    id: str
    project_id: str
    photo_id: str
    type: str
    label: str
    box: Box
    confidence: Optional[float] = None
    origin: str
    is_locked: bool
    supported: bool
    created_at: str
    updated_at: str


class ComponentUpdateResponse(BaseModel):
    """Result of updating a component, including side-effect counts."""

    component: ComponentResponse
    removed_selections: int = 0
    removed_ai_measurement: bool = False
    warnings: List[str] = Field(default_factory=list)


class ComponentListResponse(BaseModel):
    """List of components."""

    items: List[ComponentResponse]


def _clean_label(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        "".join(
            character
            for character in value
            if unicodedata.category(character) not in {"Cc", "Cf"}
        ),
    ).strip()[:120]
