"""Photo request and response schemas."""

from typing import List, Optional
from pydantic import BaseModel


class PhotoResponse(BaseModel):
    """Uploaded house photo metadata."""

    id: str
    project_id: str
    view_index: int
    facade_label: Optional[str] = None
    original_filename: str
    mime_type: str
    width_px: int
    height_px: int
    file_size_bytes: int
    quality_usable: Optional[bool] = None
    quality_reason: Optional[str] = None
    detected_at: Optional[str] = None
    image_url: str
    created_at: str


class PhotoListResponse(BaseModel):
    """List of photos for a project."""

    items: List[PhotoResponse]

