"""Project request and response schemas."""

import unicodedata
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.common import PROJECT_STEPS


class ProjectCreate(BaseModel):
    """Payload to create a new renovation project."""

    name: str = Field(..., min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_and_validate_name(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Project name cannot be empty or whitespace only")
        if any(unicodedata.category(char) == "Cc" for char in trimmed):
            raise ValueError("Project name cannot contain control characters")
        return trimmed


class ProjectUpdate(BaseModel):
    """Payload to partially update project attributes."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_step: Optional[str] = None
    active_variant_id: Optional[str] = None
    floor_count: Optional[int] = Field(None, ge=1, le=6)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            trimmed = v.strip()
            if not trimmed:
                raise ValueError("Project name cannot be empty")
            if any(unicodedata.category(char) == "Cc" for char in trimmed):
                raise ValueError("Project name cannot contain control characters")
            return trimmed
        return v

    @field_validator("last_step")
    @classmethod
    def validate_step(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PROJECT_STEPS:
            raise ValueError(f"Invalid project step: {v}")
        return v

    @model_validator(mode="after")
    def validate_patch(self) -> "ProjectUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one project field must be provided")
        if "last_step" in self.model_fields_set and self.last_step is None:
            raise ValueError("last_step cannot be null")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class ProjectResponse(BaseModel):
    """Full project view including counts."""

    id: str
    name: str
    last_step: str
    active_variant_id: Optional[str] = None
    floor_count: Optional[int] = None
    photo_count: int = 0
    component_count: int = 0
    variant_count: int = 0
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    items: List[ProjectResponse]
    total: int
