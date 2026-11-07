"""Variant and material selection schemas."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SelectionData(BaseModel):
    """Payload to assign a material to a component in a variant."""

    material_id: str
    params: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class SelectionResponse(BaseModel):
    """Component material selection record."""

    component_id: str
    material_id: str
    params: Dict[str, Any]
    updated_at: str


class VariantCreate(BaseModel):
    """Payload to create a design variant."""

    name: Optional[str] = Field(None, min_length=1, max_length=60)
    copy_from_variant_id: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Variant name cannot be empty")
        return trimmed


class VariantUpdate(BaseModel):
    """Payload to rename a variant."""

    name: str = Field(..., min_length=1, max_length=60)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Variant name cannot be empty")
        return trimmed


class VariantResponse(BaseModel):
    """Design variant response."""

    id: str
    project_id: str
    name: str
    is_active: bool
    selections: List[SelectionResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str


class VariantListResponse(BaseModel):
    """List of design variants."""

    items: List[VariantResponse]
