"""Synchronous photo component detection endpoint."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_catalogue,
    get_db,
    get_project,
    get_settings,
    get_storage,
)
from app.core.config import Settings
from app.core.storage import StorageManager
from app.schemas.detection import DetectionResponse
from app.services.detection_service import detect_components

router = APIRouter(
    prefix="/projects/{project_id}/photos/{photo_id}",
    tags=["Detection"],
)


@router.post("/detect", response_model=DetectionResponse)
def post_detection(
    project_id: str,
    photo_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> DetectionResponse:
    """Detect components in an uploaded photo."""
    return DetectionResponse(
        **detect_components(
            conn,
            storage,
            settings,
            catalogue,
            project_id,
            photo_id,
        )
    )
