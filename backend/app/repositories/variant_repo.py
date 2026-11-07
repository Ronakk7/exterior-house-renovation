"""Design variant database repository."""

import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(conn: sqlite3.Connection, project_id: str, name: str) -> Dict[str, Any]:
    """Create a new design variant for a project."""
    variant_id = generate_id("var")
    now = utc_now()

    try:
        conn.execute(
            """
            INSERT INTO variants (id, project_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (variant_id, project_id, name, now, now),
        )
    except sqlite3.IntegrityError:
        raise ConflictError(
            details={"reason": "duplicate_name"},
            message=f"A variant named '{name}' already exists in this project.",
        )

    return get_by_id(conn, variant_id, project_id)  # type: ignore


def get_by_id(
    conn: sqlite3.Connection, variant_id: str, project_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get variant by ID."""
    if project_id:
        cursor = conn.execute(
            "SELECT * FROM variants WHERE id = ? AND project_id = ?;",
            (variant_id, project_id),
        )
    else:
        cursor = conn.execute("SELECT * FROM variants WHERE id = ?;", (variant_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_by_project(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    """List variants for a project ordered by creation time."""
    cursor = conn.execute(
        "SELECT * FROM variants WHERE project_id = ? ORDER BY created_at ASC, id ASC;",
        (project_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def find_name(
    conn: sqlite3.Connection,
    project_id: str,
    name: str,
    exclude_variant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find a case-insensitive name collision in the project."""
    cursor = conn.execute(
        """
        SELECT * FROM variants
        WHERE project_id = ? AND name = ? COLLATE NOCASE
          AND (? IS NULL OR id != ?)
        LIMIT 1;
        """,
        (project_id, name, exclude_variant_id, exclude_variant_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def update(
    conn: sqlite3.Connection, variant_id: str, project_id: str, name: str
) -> Dict[str, Any]:
    """Rename a design variant."""
    try:
        cursor = conn.execute(
            """
            UPDATE variants
            SET name = ?, updated_at = ?
            WHERE id = ? AND project_id = ?;
            """,
            (name, utc_now(), variant_id, project_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("variant")
    except sqlite3.IntegrityError:
        raise ConflictError(
            details={"reason": "duplicate_name"},
            message=f"A variant named '{name}' already exists in this project.",
        )

    return get_by_id(conn, variant_id, project_id)  # type: ignore


def delete(conn: sqlite3.Connection, variant_id: str, project_id: str) -> bool:
    """Delete a variant. Raises ConflictError if it's the last remaining variant."""
    total = count_by_project(conn, project_id)
    if total <= 1:
        raise ConflictError(
            details={"reason": "last_variant"},
            message="Cannot delete the only design variant.",
        )

    # Check if this variant was active; if so, reassign to the oldest remaining variant
    proj_row = conn.execute(
        "SELECT active_variant_id FROM projects WHERE id = ?;", (project_id,)
    ).fetchone()

    cursor = conn.execute(
        "DELETE FROM variants WHERE id = ? AND project_id = ?;",
        (variant_id, project_id),
    )
    if cursor.rowcount == 0:
        raise NotFoundError("variant")

    if proj_row and proj_row["active_variant_id"] == variant_id:
        remaining = conn.execute(
            "SELECT id FROM variants WHERE project_id = ? ORDER BY created_at ASC LIMIT 1;",
            (project_id,),
        ).fetchone()
        if remaining:
            conn.execute(
                "UPDATE projects SET active_variant_id = ?, updated_at = ? WHERE id = ?;",
                (remaining["id"], utc_now(), project_id),
            )

    return True


def count_by_project(conn: sqlite3.Connection, project_id: str) -> int:
    """Count variants for project."""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM variants WHERE project_id = ?;", (project_id,)
    )
    return cursor.fetchone()[0]


def touch_updated_at(conn: sqlite3.Connection, variant_id: str) -> None:
    conn.execute(
        "UPDATE variants SET updated_at = ? WHERE id = ?;",
        (utc_now(), variant_id),
    )
