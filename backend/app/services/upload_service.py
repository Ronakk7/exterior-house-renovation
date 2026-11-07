"""Project photo validation, storage, and lifecycle operations."""

import logging
import re
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings
from app.core.database import transaction
from app.core.errors import AppError, ConflictError, NotFoundError, UploadError
from app.core.ids import generate_id
from app.core.storage import StorageManager
from app.repositories import generation_repo, photo_repo, project_repo

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
CONTENT_LENGTH_OVERHEAD = 1024 * 1024
IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
UPLOAD_MESSAGES = {
    "UPLOAD_INVALID_TYPE": (
        "This file type is not supported. Please upload a JPG, PNG or WebP photo."
    ),
    "UPLOAD_TOO_SMALL": (
        "This photo is too small ({width} x {height}). Please upload one at least "
        "{minimum} pixels on its shorter side."
    ),
    "UPLOAD_CORRUPT": "We could not read this image. Please try a different photo.",
}


def validate_content_length(settings: Settings, content_length: str | None) -> None:
    if not content_length:
        return
    try:
        declared_length = int(content_length)
    except ValueError:
        return
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if declared_length > max_bytes + CONTENT_LENGTH_OVERHEAD:
        raise UploadError(
            "UPLOAD_TOO_LARGE",
            f"This photo is too large. Please upload a file under {settings.MAX_UPLOAD_MB} MB.",
        )


def _read_upload(file: BinaryIO, settings: Settings, content_length: str | None) -> bytes:
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    validate_content_length(settings, content_length)

    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadError(
                "UPLOAD_TOO_LARGE",
                f"This photo is too large. Please upload a file under {settings.MAX_UPLOAD_MB} MB.",
            )
        chunks.append(chunk)
    if total == 0:
        raise AppError(
            "VALIDATION_ERROR",
            "A photo is required.",
            422,
            {"fields": [{"field": "file", "problem": "a photo is required"}]},
        )
    return b"".join(chunks)


def _validate_image(data: bytes, settings: Settings) -> Tuple[str, str, int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format or ""
            width, height = image.size
            frame_count = getattr(image, "n_frames", 1)

            if image_format not in IMAGE_FORMATS:
                raise UploadError(
                    "UPLOAD_INVALID_TYPE", UPLOAD_MESSAGES["UPLOAD_INVALID_TYPE"]
                )
            mime_type, extension = IMAGE_FORMATS[image_format]
            if mime_type not in settings.allowed_image_types_list or frame_count != 1:
                raise UploadError(
                    "UPLOAD_INVALID_TYPE", UPLOAD_MESSAGES["UPLOAD_INVALID_TYPE"]
                )
            if width * height > settings.MAX_IMAGE_PIXELS:
                raise UploadError(
                    "UPLOAD_TOO_LARGE",
                    "This photo's dimensions are too large. Please resize it and try again.",
                )
            image.verify()

        with Image.open(BytesIO(data)) as image:
            image.load()
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
    except UploadError:
        raise
    except Image.DecompressionBombError as exc:
        raise UploadError(
            "UPLOAD_TOO_LARGE",
            "This photo's dimensions are too large. Please resize it and try again.",
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as exc:
        raise UploadError(
            "UPLOAD_CORRUPT", UPLOAD_MESSAGES["UPLOAD_CORRUPT"]
        ) from exc

    if min(width, height) < settings.MIN_IMAGE_SHORT_SIDE_PX:
        raise UploadError(
            "UPLOAD_TOO_SMALL",
            UPLOAD_MESSAGES["UPLOAD_TOO_SMALL"].format(
                width=width,
                height=height,
                minimum=settings.MIN_IMAGE_SHORT_SIDE_PX,
            ),
        )
    return mime_type, extension, width, height


def _safe_original_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:120] or "photo"


def _photo_response(photo: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(photo)
    result["image_url"] = (
        f"/api/projects/{photo['project_id']}/photos/{photo['id']}/image"
    )
    return result


def upload_photo(
    conn: sqlite3.Connection,
    storage: StorageManager,
    settings: Settings,
    project_id: str,
    file: BinaryIO,
    filename: str | None,
    content_length: str | None = None,
) -> Dict[str, Any]:
    """Validate and atomically attach an uploaded image to a project."""
    data = _read_upload(file, settings, content_length)
    mime_type, extension, width, height = _validate_image(data, settings)
    photo_id = generate_id("pho")
    stored_path = storage.project_path(
        project_id, "original", f"{photo_id}.{extension}"
    )
    original_filename = _safe_original_filename(filename)

    try:
        storage.save_bytes(stored_path, data)
    except OSError as exc:
        logger.exception("Could not store uploaded photo", extra={"project_id": project_id})
        raise AppError(
            "INTERNAL_ERROR",
            "Something went wrong on our side. Please try again.",
            500,
        ) from exc

    try:
        with transaction(conn, immediate=True):
            if project_repo.get_by_id(conn, project_id) is None:
                raise NotFoundError("project")
            if photo_repo.count_by_project(conn, project_id) >= settings.MAX_PHOTOS_PER_PROJECT:
                raise ConflictError(
                    code="PHOTO_LIMIT_REACHED",
                    message="This project already has a photo. Delete it first to upload a different one.",
                )
            view_index = photo_repo.get_next_view_index(conn, project_id)
            photo = photo_repo.create(
                conn=conn,
                project_id=project_id,
                view_index=view_index,
                original_filename=original_filename,
                stored_path=stored_path,
                mime_type=mime_type,
                width_px=width,
                height_px=height,
                file_size_bytes=len(data),
                photo_id=photo_id,
            )
            project_repo.touch_updated_at(conn, project_id)
    except Exception:
        try:
            storage.delete_file(stored_path)
        except OSError:
            logger.warning(
                "Could not remove uncommitted uploaded photo",
                extra={"project_id": project_id},
                exc_info=True,
            )
        raise

    return _photo_response(photo)


def list_photos(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    return [
        _photo_response(photo)
        for photo in photo_repo.list_by_project(conn, project_id)
    ]


def get_photo_image(
    conn: sqlite3.Connection,
    storage: StorageManager,
    project_id: str,
    photo_id: str,
) -> Tuple[Dict[str, Any], Path]:
    photo = photo_repo.get_by_id(conn, photo_id, project_id)
    if photo is None:
        raise NotFoundError("photo")
    try:
        image_path = storage.get_file_path(photo["stored_path"])
    except NotFoundError as exc:
        logger.warning(
            "Photo database row has no stored file",
            extra={"project_id": project_id, "photo_id": photo_id},
        )
        raise NotFoundError("photo") from exc
    return photo, image_path


def delete_photo(
    conn: sqlite3.Connection,
    storage: StorageManager,
    project_id: str,
    photo_id: str,
) -> None:
    with transaction(conn, immediate=True):
        photo = photo_repo.get_by_id(conn, photo_id, project_id)
        if photo is None:
            raise NotFoundError("photo")
        generated_paths = generation_repo.list_image_paths_by_photo(
            conn, project_id, photo_id
        )
        photo_repo.delete(conn, photo_id, project_id)
        project_repo.touch_updated_at(conn, project_id)

    for path in [photo["stored_path"], *generated_paths]:
        try:
            storage.delete_file(path)
        except OSError:
            logger.warning(
                "Could not remove photo-related file",
                extra={"project_id": project_id, "photo_id": photo_id},
                exc_info=True,
            )
