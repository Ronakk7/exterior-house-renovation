"""Project database repository."""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(conn: sqlite3.Connection, name: str) -> Dict[str, Any]:
    """Create a new project and initialize its default variant 'Design 1'."""
    project_id = generate_id("prj")
    variant_id = generate_id("var")
    now = utc_now()

    conn.execute(
        """
        INSERT INTO projects (id, name, last_step, active_variant_id, floor_count, created_at, updated_at)
        VALUES (?, ?, 'upload', ?, NULL, ?, ?);
        """,
        (project_id, name, variant_id, now, now),
    )
    conn.execute(
        """
        INSERT INTO variants (id, project_id, name, created_at, updated_at)
        VALUES (?, ?, 'Design 1', ?, ?);
        """,
        (variant_id, project_id, now, now),
    )
    return get_by_id(conn, project_id)  # type: ignore


def get_by_id(conn: sqlite3.Connection, project_id: str) -> Optional[Dict[str, Any]]:
    """Get project by ID with derived counts."""
    cursor = conn.execute(
        """
        SELECT p.*,
               (SELECT COUNT(*) FROM photos ph WHERE ph.project_id = p.id) as photo_count,
               (SELECT COUNT(*) FROM components c WHERE c.project_id = p.id) as component_count,
               (SELECT COUNT(*) FROM variants v WHERE v.project_id = p.id) as variant_count
        FROM projects p
        WHERE p.id = ?;
        """,
        (project_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_all(
    conn: sqlite3.Connection, limit: int = 50, offset: int = 0
) -> Tuple[List[Dict[str, Any]], int]:
    """List projects ordered by updated_at descending with total count."""
    count_cursor = conn.execute("SELECT COUNT(*) FROM projects;")
    total = count_cursor.fetchone()[0]

    cursor = conn.execute(
        """
        SELECT p.*,
               (SELECT COUNT(*) FROM photos ph WHERE ph.project_id = p.id) as photo_count,
               (SELECT COUNT(*) FROM components c WHERE c.project_id = p.id) as component_count,
               (SELECT COUNT(*) FROM variants v WHERE v.project_id = p.id) as variant_count
        FROM projects p
        ORDER BY p.updated_at DESC, p.id ASC
        LIMIT ? OFFSET ?;
        """,
        (limit, offset),
    )
    items = [dict(row) for row in cursor.fetchall()]
    return items, total


def update(conn: sqlite3.Connection, project_id: str, **fields: Any) -> Dict[str, Any]:
    """Update project fields and touch updated_at."""
    if not fields:
        existing = get_by_id(conn, project_id)
        if not existing:
            raise NotFoundError("project")
        return existing

    # Validate active_variant_id belongs to this project if updated
    if "active_variant_id" in fields and fields["active_variant_id"] is not None:
        check = conn.execute(
            "SELECT id FROM variants WHERE id = ? AND project_id = ?;",
            (fields["active_variant_id"], project_id),
        ).fetchone()
        if not check:
            raise NotFoundError(
                "variant", "Active variant does not belong to this project."
            )

    if any(field != "last_step" for field in fields):
        fields["updated_at"] = utc_now()
    set_clauses = [f"{k} = ?" for k in fields.keys()]
    values = list(fields.values()) + [project_id]

    try:
        cursor = conn.execute(
            f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = ?;",
            values,
        )
        if cursor.rowcount == 0:
            raise NotFoundError("project")
    except sqlite3.IntegrityError as e:
        raise ConflictError(message=str(e))

    return get_by_id(conn, project_id)  # type: ignore


def delete(conn: sqlite3.Connection, project_id: str) -> bool:
    """Delete project by ID (cascades all children in DB)."""
    cursor = conn.execute("DELETE FROM projects WHERE id = ?;", (project_id,))
    if cursor.rowcount == 0:
        raise NotFoundError("project")
    return True


def touch_updated_at(conn: sqlite3.Connection, project_id: str) -> None:
    """Touch project updated_at timestamp."""
    conn.execute(
        "UPDATE projects SET updated_at = ? WHERE id = ?;",
        (utc_now(), project_id),
    )
