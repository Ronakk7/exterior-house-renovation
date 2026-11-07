"""Photo database repository."""

import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(
    conn: sqlite3.Connection,
    project_id: str,
    view_index: int,
    original_filename: str,
    stored_path: str,
    mime_type: str,
    width_px: int,
    height_px: int,
    file_size_bytes: int,
    facade_label: Optional[str] = None,
    photo_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a photo record for a project."""
    photo_id = photo_id or generate_id("pho")
    now = utc_now()
    try:
        conn.execute(
            """
            INSERT INTO photos (
                id, project_id, view_index, facade_label, original_filename,
                stored_path, mime_type, width_px, height_px, file_size_bytes,
                quality_usable, quality_reason, detected_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?);
            """,
            (
                photo_id,
                project_id,
                view_index,
                facade_label,
                original_filename,
                stored_path,
                mime_type,
                width_px,
                height_px,
                file_size_bytes,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ConflictError(
            code="PHOTO_LIMIT_REACHED",
            message="This project already has the maximum number of photos.",
        ) from exc

    return get_by_id(conn, photo_id, project_id)  # type: ignore


def get_by_id(
    conn: sqlite3.Connection, photo_id: str, project_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get photo by ID with optional project ownership check."""
    if project_id:
        cursor = conn.execute(
            "SELECT * FROM photos WHERE id = ? AND project_id = ?;",
            (photo_id, project_id),
        )
    else:
        cursor = conn.execute("SELECT * FROM photos WHERE id = ?;", (photo_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_by_project(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    """List photos for a project ordered by view_index."""
    cursor = conn.execute(
        "SELECT * FROM photos WHERE project_id = ? ORDER BY view_index ASC;",
        (project_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def update_quality(
    conn: sqlite3.Connection,
    photo_id: str,
    quality_usable: bool,
    quality_reason: Optional[str] = None,
    detected_at: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update photo detection quality flags."""
    now = detected_at or utc_now()
    usable_int = 1 if quality_usable else 0
    if project_id is None:
        cursor = conn.execute(
            """
            UPDATE photos
            SET quality_usable = ?, quality_reason = ?, detected_at = ?
            WHERE id = ?;
            """,
            (usable_int, quality_reason, now, photo_id),
        )
    else:
        cursor = conn.execute(
            """
            UPDATE photos
            SET quality_usable = ?, quality_reason = ?, detected_at = ?
            WHERE id = ? AND project_id = ?;
            """,
            (usable_int, quality_reason, now, photo_id, project_id),
        )
    if cursor.rowcount == 0:
        raise NotFoundError("photo")
    return get_by_id(conn, photo_id, project_id)  # type: ignore


def delete(conn: sqlite3.Connection, photo_id: str, project_id: str) -> bool:
    """Delete a photo record."""
    cursor = conn.execute(
        "DELETE FROM photos WHERE id = ? AND project_id = ?;",
        (photo_id, project_id),
    )
    if cursor.rowcount == 0:
        raise NotFoundError("photo")
    return True


def count_by_project(conn: sqlite3.Connection, project_id: str) -> int:
    """Return count of photos in project."""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM photos WHERE project_id = ?;", (project_id,)
    )
    return cursor.fetchone()[0]


def get_next_view_index(conn: sqlite3.Connection, project_id: str) -> int:
    """Return the next available view index for a project."""
    cursor = conn.execute(
        "SELECT view_index FROM photos WHERE project_id = ?;",
        (project_id,),
    )
    used = {row["view_index"] for row in cursor.fetchall()}
    for view_index in range(1, len(used) + 2):
        if view_index not in used:
            return view_index
    raise ConflictError(
        code="PHOTO_LIMIT_REACHED",
        message="This project already has the maximum number of photos.",
    )
