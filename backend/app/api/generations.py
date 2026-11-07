"""Redesign generation lifecycle and image retrieval routes."""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse

from app.api.deps import get_catalogue, get_db, get_project, get_settings, get_storage
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.storage import StorageManager
from app.repositories import generation_repo, variant_repo
from app.schemas.generations import (
    GenerationApproval,
    GenerationCreate,
    GenerationDetailResponse,
    GenerationListResponse,
    GenerationResponse,
)
from app.services import redesign_service

router = APIRouter(tags=["Redesign"])


@router.post(
    "/projects/{project_id}/variants/{variant_id}/generations",
    response_model=GenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_generation(
    project_id: str,
    variant_id: str,
    payload: GenerationCreate,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: StorageManager = Depends(get_storage),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> GenerationResponse:
    return GenerationResponse(
        **redesign_service.create_generation(
            conn,
            settings,
            storage,
            project_id,
            variant_id,
            catalogue,
            payload.photo_id,
            payload.extra_instructions,
        )
    )


@router.get(
    "/projects/{project_id}/generations",
    response_model=GenerationListResponse,
)
def list_generations(
    project_id: str,
    variant_id: Optional[str] = Query(None),
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> GenerationListResponse:
    if variant_id and variant_repo.get_by_id(conn, variant_id, project_id) is None:
        raise NotFoundError("variant")
    return GenerationListResponse(
        **redesign_service.list_generations(
            conn, project_id, catalogue, variant_id
        )
    )


@router.get(
    "/projects/{project_id}/generations/{generation_id}",
    response_model=GenerationDetailResponse,
)
def get_generation(
    project_id: str,
    generation_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> GenerationDetailResponse:
    return GenerationDetailResponse(
        **redesign_service.get_generation(
            conn, project_id, generation_id, catalogue
        )
    )


@router.patch(
    "/projects/{project_id}/generations/{generation_id}",
    response_model=GenerationResponse,
)
def update_generation_approval(
    project_id: str,
    generation_id: str,
    payload: GenerationApproval,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> GenerationResponse:
    return GenerationResponse(
        **redesign_service.update_approval(
            conn,
            project_id,
            generation_id,
            payload.is_approved,
            catalogue,
        )
    )


@router.delete(
    "/projects/{project_id}/generations/{generation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_generation(
    project_id: str,
    generation_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> None:
    redesign_service.delete_generation(conn, storage, project_id, generation_id)


@router.get("/projects/{project_id}/generations/{generation_id}/image")
def get_generation_image(
    project_id: str,
    generation_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> FileResponse:
    generation = generation_repo.get_by_id(conn, generation_id, project_id)
    if generation is None or generation["status"] != "succeeded" or not generation.get("image_path"):
        raise NotFoundError("generation")
    file_path = storage.get_file_path(generation["image_path"])
    return FileResponse(
        path=Path(file_path),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
