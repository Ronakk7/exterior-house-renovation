"""System health, client configuration, and stage run debug endpoints."""

import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_catalogue, get_db, get_project, get_settings
from app.core.config import Settings
from app.repositories import stage_run_repo
from app.schemas.common import COMPONENT_TYPES
from app.schemas.stage_runs import StageRunListResponse, StageRunResponse
from app.schemas.system import (
    ClientConfigResponse,
    ComponentTypeInfo,
    HealthResponse,
    LimitsConfig,
    UploadConfig,
)
from app.services.catalogue_compatibility import supported_component_types

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
def get_health(
    settings: Settings = Depends(get_settings),
    conn: sqlite3.Connection = Depends(get_db),
) -> HealthResponse:
    """Liveness check and configuration sanity check."""
    # Check DB accessibility
    cursor = conn.execute("SELECT 1;")
    db_status = "ok" if cursor.fetchone()[0] == 1 else "error"

    return HealthResponse(
        status="ok",
        version="0.1.0",
        database=db_status,
        ai_mock_mode=settings.AI_MOCK_MODE,
        ai_configured=settings.ai_configured,
    )


@router.get("/client-config", response_model=ClientConfigResponse)
def get_client_config(
    settings: Settings = Depends(get_settings),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> ClientConfigResponse:
    """Return application limits, component vocabulary, and configuration for frontend."""
    # Compute component types support from catalogue
    all_compat_types = supported_component_types(catalogue)

    component_type_info_list: List[ComponentTypeInfo] = []
    for ctype in COMPONENT_TYPES:
        label = ctype.replace("_", " ").capitalize()
        supported = ctype in all_compat_types
        component_type_info_list.append(
            ComponentTypeInfo(type=ctype, label=label, supported=supported)
        )

    return ClientConfigResponse(
        app_name="Exterior Renovation Planner",
        currency=settings.CURRENCY,
        currency_symbol=settings.CURRENCY_SYMBOL,
        upload=UploadConfig(
            max_upload_mb=settings.MAX_UPLOAD_MB,
            allowed_mime_types=settings.allowed_image_types_list,
            min_short_side_px=settings.MIN_IMAGE_SHORT_SIDE_PX,
            max_photos_per_project=settings.MAX_PHOTOS_PER_PROJECT,
        ),
        component_types=component_type_info_list,
        limits=LimitsConfig(
            extra_instructions_max_chars=500,
            project_name_max_chars=100,
            max_components_per_photo=settings.MAX_COMPONENTS_PER_PHOTO,
        ),
        ai_mock_mode=settings.AI_MOCK_MODE,
    )


@router.get("/projects/{project_id}/stage-runs", response_model=StageRunListResponse)
def list_stage_runs(
    project_id: str,
    stage: Optional[str] = Query(None, description="Optional stage filter"),
    project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> StageRunListResponse:
    """Return execution history for asynchronous / AI stages."""
    runs = stage_run_repo.list_by_project(conn, project_id, stage=stage, limit=50)
    return StageRunListResponse(
        items=[StageRunResponse(**run) for run in runs]
    )
