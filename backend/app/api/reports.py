"""PDF report generation, listing, and download endpoints."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_catalogue, get_db, get_project, get_settings, get_storage
from app.core.config import Settings
from app.core.storage import StorageManager
from app.schemas.reports import ReportCreate, ReportListResponse, ReportResponse
from app.services import report_service

router = APIRouter(tags=["Reports"])


@router.post(
    "/projects/{project_id}/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    payload: ReportCreate,
    project_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
    settings: Settings = Depends(get_settings),
) -> ReportResponse:
    return ReportResponse(**report_service.create_report(
        conn,
        storage,
        project_id,
        payload.variant_id,
        payload.generation_id,
        catalogue,
        settings.CURRENCY,
    ))


@router.get(
    "/projects/{project_id}/reports",
    response_model=ReportListResponse,
)
def list_reports(
    project_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> ReportListResponse:
    return ReportListResponse(**report_service.list_reports(conn, project_id))


@router.get("/projects/{project_id}/reports/{report_id}/download")
def download_report(
    project_id: str,
    report_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> Response:
    content, filename = report_service.get_report_download(
        conn, storage, project_id, report_id
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
