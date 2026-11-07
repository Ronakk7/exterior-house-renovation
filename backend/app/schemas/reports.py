"""PDF Report request and response schemas."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class ReportCreate(BaseModel):
    """Payload to trigger report generation."""

    variant_id: Optional[str] = None
    generation_id: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class ReportResponse(BaseModel):
    """Report metadata view."""

    id: str
    project_id: str
    variant_id: Optional[str] = None
    generation_id: Optional[str] = None
    grand_total: float
    currency: str
    download_url: str
    created_at: str


class ReportListResponse(BaseModel):
    """List of generated reports for a project."""

    items: List[ReportResponse]

