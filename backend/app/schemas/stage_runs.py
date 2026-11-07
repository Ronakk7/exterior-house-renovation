"""Stage run debug log schemas."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class StageRunResponse(BaseModel):
    """Execution log record for long-running AI or PDF stages."""

    id: str
    stage: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    detail: Dict[str, Any]


class StageRunListResponse(BaseModel):
    """List of stage execution logs."""

    items: List[StageRunResponse]

