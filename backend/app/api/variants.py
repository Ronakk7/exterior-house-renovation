"""Design variant and material selection routes."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, status

from app.api.deps import get_catalogue, get_db, get_project, get_storage
from app.core.storage import StorageManager
from app.schemas.variants import (
    SelectionData,
    SelectionResponse,
    VariantCreate,
    VariantListResponse,
    VariantResponse,
    VariantUpdate,
)
from app.services import variant_service

router = APIRouter(prefix="/projects/{project_id}/variants", tags=["Variants"])


@router.get("", response_model=VariantListResponse)
def list_variants(
    project_id: str,
    project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> VariantListResponse:
    return VariantListResponse(
        **variant_service.list_variants(
            conn, project_id, project.get("active_variant_id")
        )
    )


@router.post("", response_model=VariantResponse, status_code=status.HTTP_201_CREATED)
def create_variant(
    project_id: str,
    payload: VariantCreate,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> VariantResponse:
    return VariantResponse(
        **variant_service.create_variant(
            conn,
            project_id,
            payload.name,
            payload.copy_from_variant_id,
        )
    )


@router.patch("/{variant_id}", response_model=VariantResponse)
def rename_variant(
    project_id: str,
    variant_id: str,
    payload: VariantUpdate,
    project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> VariantResponse:
    result = variant_service.rename_variant(
        conn, project_id, variant_id, payload.name
    )
    result["is_active"] = result["id"] == project.get("active_variant_id")
    return VariantResponse(**result)


@router.delete("/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variant(
    project_id: str,
    variant_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> None:
    variant_service.delete_variant(conn, storage, project_id, variant_id)


@router.put(
    "/{variant_id}/selections/{component_id}",
    response_model=SelectionResponse,
)
def set_selection(
    project_id: str,
    variant_id: str,
    component_id: str,
    payload: SelectionData,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> SelectionResponse:
    return SelectionResponse(
        **variant_service.set_selection(
            conn,
            project_id,
            variant_id,
            component_id,
            payload.model_dump(),
            catalogue,
        )
    )


@router.delete(
    "/{variant_id}/selections/{component_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_selection(
    project_id: str,
    variant_id: str,
    component_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> None:
    variant_service.remove_selection(
        conn, project_id, variant_id, component_id
    )
