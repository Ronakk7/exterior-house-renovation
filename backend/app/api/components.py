"""Component list, create, update and delete routes."""

import sqlite3
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_catalogue, get_db, get_project, get_settings
from app.core.config import Settings
from app.schemas.components import (
    ComponentCreate,
    ComponentListResponse,
    ComponentResponse,
    ComponentUpdate,
    ComponentUpdateResponse,
)
from app.services import component_service

router = APIRouter(prefix="/projects/{project_id}/components", tags=["Components"])


@router.get("", response_model=ComponentListResponse)
def get_components(
    project_id: str,
    photo_id: Optional[str] = Query(None),
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> ComponentListResponse:
    return ComponentListResponse(
        **component_service.list_components(conn, project_id, catalogue, photo_id)
    )


@router.post("", response_model=ComponentResponse, status_code=status.HTTP_201_CREATED)
def post_component(
    project_id: str,
    payload: ComponentCreate,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> ComponentResponse:
    return ComponentResponse(
        **component_service.create_component(
            conn,
            settings,
            project_id,
            catalogue,
            payload.photo_id,
            payload.type,
            payload.label,
            payload.box,
        )
    )


@router.patch("/{component_id}", response_model=ComponentUpdateResponse)
def patch_component(
    project_id: str,
    component_id: str,
    payload: ComponentUpdate,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> ComponentUpdateResponse:
    return ComponentUpdateResponse(
        **component_service.update_component(
            conn,
            project_id,
            component_id,
            catalogue,
            payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_component(
    project_id: str,
    component_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> None:
    component_service.delete_component(conn, project_id, component_id)
