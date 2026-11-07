"""AI Generation repository."""

import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(
    conn: sqlite3.Connection,
    project_id: str,
    variant_id: str,
    photo_id: str,
    input_fingerprint: str,
    prompt_text: str,
    extra_instructions: Optional[str],
    model_name: str,
) -> Dict[str, Any]:
    """Create a new generation record in 'running' state."""
    gen_id = generate_id("gen")
    now = utc_now()

    conn.execute(
        """
        INSERT INTO generations (
            id, project_id, variant_id, photo_id, status, input_fingerprint,
            prompt_text, extra_instructions, model_name, image_path, width_px,
            height_px, is_approved, error_code, error_message, created_at,
            completed_at, duration_ms
        ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, NULL, ?, NULL, NULL);
        """,
        (
            gen_id,
            project_id,
            variant_id,
            photo_id,
            input_fingerprint,
            prompt_text,
            extra_instructions,
            model_name,
            now,
        ),
    )
    return get_by_id(conn, gen_id, project_id)  # type: ignore


def get_by_id(
    conn: sqlite3.Connection, generation_id: str, project_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get generation by ID."""
    if project_id:
        cursor = conn.execute(
            "SELECT * FROM generations WHERE id = ? AND project_id = ?;",
            (generation_id, project_id),
        )
    else:
        cursor = conn.execute(
            "SELECT * FROM generations WHERE id = ?;", (generation_id,)
        )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_by_project(
    conn: sqlite3.Connection, project_id: str, variant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List generations newest first, optionally filtered by variant."""
    if variant_id:
        cursor = conn.execute(
            """
            SELECT id, project_id, variant_id, photo_id, status, input_fingerprint,
                   extra_instructions, model_name, image_path, width_px, height_px,
                   is_approved, error_code, error_message, created_at, completed_at, duration_ms
            FROM generations
            WHERE project_id = ? AND variant_id = ?
            ORDER BY created_at DESC, rowid DESC;
            """,
            (project_id, variant_id),
        )
    else:
        cursor = conn.execute(
            """
            SELECT id, project_id, variant_id, photo_id, status, input_fingerprint,
                   extra_instructions, model_name, image_path, width_px, height_px,
                   is_approved, error_code, error_message, created_at, completed_at, duration_ms
            FROM generations
            WHERE project_id = ?
            ORDER BY created_at DESC, rowid DESC;
            """,
            (project_id,),
        )
    return [dict(row) for row in cursor.fetchall()]


def list_image_paths_by_photo(
    conn: sqlite3.Connection, project_id: str, photo_id: str
) -> List[str]:
    """Return generated-image paths for generations that will cascade with a photo."""
    cursor = conn.execute(
        """
        SELECT image_path FROM generations
        WHERE project_id = ? AND photo_id = ? AND image_path IS NOT NULL;
        """,
        (project_id, photo_id),
    )
    return [row["image_path"] for row in cursor.fetchall()]


def list_image_paths_by_variant(
    conn: sqlite3.Connection, project_id: str, variant_id: str
) -> List[str]:
    """Return generated-image paths for a variant before cascading its rows."""
    cursor = conn.execute(
        """
        SELECT image_path FROM generations
        WHERE project_id = ? AND variant_id = ? AND image_path IS NOT NULL;
        """,
        (project_id, variant_id),
    )
    return [row["image_path"] for row in cursor.fetchall()]


def update_completed(
    conn: sqlite3.Connection,
    generation_id: str,
    status: str,
    image_path: Optional[str] = None,
    width_px: Optional[int] = None,
    height_px: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Mark generation completed (succeeded or failed)."""
    now = utc_now()
    cursor = conn.execute(
        """
        UPDATE generations
        SET status = ?,
            image_path = ?,
            width_px = ?,
            height_px = ?,
            error_code = ?,
            error_message = ?,
            completed_at = ?,
            duration_ms = ?
        WHERE id = ?;
        """,
        (
            status,
            image_path,
            width_px,
            height_px,
            error_code,
            error_message,
            now,
            duration_ms,
            generation_id,
        ),
    )
    if cursor.rowcount == 0:
        raise NotFoundError("generation")
    return get_by_id(conn, generation_id)  # type: ignore


def update_approval(
    conn: sqlite3.Connection, generation_id: str, project_id: str, is_approved: bool
) -> Dict[str, Any]:
    """Toggle approval for a generation. If approving, clears approval on other generations of the same variant."""
    gen = get_by_id(conn, generation_id, project_id)
    if not gen:
        raise NotFoundError("generation")

    if is_approved and gen["status"] != "succeeded":
        raise ConflictError(
            details={"reason": "not_succeeded"},
            message="Only succeeded generations can be approved.",
        )

    if is_approved:
        # Clear approval on siblings in the same variant
        conn.execute(
            "UPDATE generations SET is_approved = 0 WHERE variant_id = ? AND project_id = ?;",
            (gen["variant_id"], project_id),
        )

    val = 1 if is_approved else 0
    conn.execute(
        "UPDATE generations SET is_approved = ? WHERE id = ?;", (val, generation_id)
    )
    return get_by_id(conn, generation_id, project_id)  # type: ignore


def delete(conn: sqlite3.Connection, generation_id: str, project_id: str) -> Optional[str]:
    """Delete a generation record. Returns image_path if it had one, so file can be removed."""
    gen = get_by_id(conn, generation_id, project_id)
    if not gen:
        raise NotFoundError("generation")
    conn.execute("DELETE FROM generations WHERE id = ?;", (generation_id,))
    return gen["image_path"]


def has_running(conn: sqlite3.Connection, project_id: str) -> bool:
    """Check if project currently has a running generation."""
    cursor = conn.execute(
        "SELECT 1 FROM generations WHERE project_id = ? AND status = 'running' LIMIT 1;",
        (project_id,),
    )
    return cursor.fetchone() is not None
