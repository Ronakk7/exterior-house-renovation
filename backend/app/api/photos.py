"""Project photo upload and retrieval routes."""

import sqlite3

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request as StarletteRequest

from app.api.deps import get_db, get_project, get_settings, get_storage
from app.core.config import Settings
from app.core.errors import AppError
from app.core.storage import StorageManager
from app.schemas.photos import PhotoListResponse, PhotoResponse
from app.services import upload_service

router = APIRouter(prefix="/projects/{project_id}/photos", tags=["Photos"])


@router.post("", response_model=PhotoResponse, status_code=status.HTTP_201_CREATED)
async def upload_photo(
    request: Request,
    project_id: str,
    _project: dict = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> PhotoResponse:
    """Validate and store one project photo."""
    upload_service.validate_content_length(
        settings, request.headers.get("content-length")
    )
    received_bytes = 0
    max_request_bytes = (
        settings.MAX_UPLOAD_MB * 1024 * 1024
        + upload_service.CONTENT_LENGTH_OVERHEAD
    )

    async def limited_receive():
        nonlocal received_bytes
        message = await request.receive()
        if message["type"] == "http.request":
            received_bytes += len(message.get("body", b""))
            if received_bytes > max_request_bytes:
                upload_service.validate_content_length(
                    settings, str(received_bytes)
                )
        return message

    form_request = StarletteRequest(request.scope, receive=limited_receive)
    try:
        form = await form_request.form()
    except StarletteHTTPException as exc:
        if exc.status_code != 400:
            raise
        raise AppError(
            "VALIDATION_ERROR",
            "The upload request is invalid. Please choose one image file.",
            422,
            {"fields": [{"field": "file", "problem": "a photo is required"}]},
        ) from exc
    try:
        entries = form.multi_items()
        if (
            len(entries) != 1
            or entries[0][0] != "file"
            or not isinstance(entries[0][1], UploadFile)
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "A photo is required.",
                422,
                {"fields": [{"field": "file", "problem": "a photo is required"}]},
            )
        file = entries[0][1]
        photo = await run_in_threadpool(
            upload_service.upload_photo,
            conn,
            storage,
            settings,
            project_id,
            file.file,
            file.filename,
            None,
        )
    finally:
        await form.close()
    return PhotoResponse(**photo)


@router.get("", response_model=PhotoListResponse)
def list_project_photos(
    project_id: str,
    _project: dict = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> PhotoListResponse:
    """List a project's photos in view order."""
    photos = upload_service.list_photos(conn, project_id)
    return PhotoListResponse(items=[PhotoResponse(**photo) for photo in photos])


@router.get("/{photo_id}/image")
def get_project_photo_image(
    project_id: str,
    photo_id: str,
    _project: dict = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> FileResponse:
    """Stream the original image with its verified media type."""
    photo, image_path = upload_service.get_photo_image(
        conn, storage, project_id, photo_id
    )
    return FileResponse(
        image_path,
        media_type=photo["mime_type"],
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_photo(
    project_id: str,
    photo_id: str,
    _project: dict = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    storage: StorageManager = Depends(get_storage),
) -> None:
    """Delete a photo and its cascading data and generated-image files."""
    upload_service.delete_photo(conn, storage, project_id, photo_id)
