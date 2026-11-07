"""Project CRUD API routes."""

import sqlite3
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, status
from app.api.deps import get_db, get_project, get_storage
from app.core.storage import StorageManager
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate,
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> ProjectResponse:
    """Create a new renovation project."""
    project = project_service.create_project(conn, storage, data.name)
    return ProjectResponse(**project)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
) -> ProjectListResponse:
    """List projects ordered by updated_at descending."""
    items, total = project_service.list_projects(conn, limit=limit, offset=offset)
    return ProjectListResponse(
        items=[ProjectResponse(**item) for item in items],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project_by_id(
    project_id: str,
    project: Dict[str, Any] = Depends(get_project),
) -> ProjectResponse:
    """Get project details."""
    return ProjectResponse(**project)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    data: ProjectUpdate,
    project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> ProjectResponse:
    """Partially update project details."""
    update_data = data.model_dump(exclude_unset=True)
    updated = project_service.update_project(conn, project_id, **update_data)
    return ProjectResponse(**updated)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> None:
    """Delete project and all its associated photos, generations, and reports."""
    project_service.delete_project(conn, storage, project_id)

