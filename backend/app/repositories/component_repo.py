"""Component and detected component database repository."""

import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(
    conn: sqlite3.Connection,
    project_id: str,
    photo_id: str,
    component_type: str,
    label: str,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
    confidence: Optional[float] = None,
    origin: str = "user",
    source_detection_id: Optional[str] = None,
    is_locked: int = 1,
) -> Dict[str, Any]:
    """Insert a working component."""
    component_id = generate_id("cmp")
    now = utc_now()

    conn.execute(
        """
        INSERT INTO components (
            id, project_id, photo_id, type, label, box_x, box_y, box_w, box_h,
            confidence, origin, source_detection_id, is_locked, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            component_id,
            project_id,
            photo_id,
            component_type,
            label,
            box_x,
            box_y,
            box_w,
            box_h,
            confidence,
            origin,
            source_detection_id,
            is_locked,
            now,
            now,
        ),
    )
    return get_by_id(conn, component_id, project_id)  # type: ignore


def get_by_id(
    conn: sqlite3.Connection, component_id: str, project_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get component by ID with optional project ownership check."""
    if project_id:
        cursor = conn.execute(
            "SELECT * FROM components WHERE id = ? AND project_id = ?;",
            (component_id, project_id),
        )
    else:
        cursor = conn.execute(
            "SELECT * FROM components WHERE id = ?;", (component_id,)
        )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_by_project(
    conn: sqlite3.Connection, project_id: str, photo_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List components for a project, optionally filtered by photo."""
    if photo_id:
        cursor = conn.execute(
            "SELECT * FROM components WHERE project_id = ? AND photo_id = ? ORDER BY created_at ASC, id ASC;",
            (project_id, photo_id),
        )
    else:
        cursor = conn.execute(
            "SELECT * FROM components WHERE project_id = ? ORDER BY created_at ASC, id ASC;",
            (project_id,),
        )
    return [dict(row) for row in cursor.fetchall()]


def update(
    conn: sqlite3.Connection, component_id: str, project_id: str, **fields: Any
) -> Dict[str, Any]:
    """Update component fields. Automatically sets is_locked = 1."""
    fields["is_locked"] = 1
    fields["updated_at"] = utc_now()

    set_clauses = [f"{k} = ?" for k in fields.keys()]
    values = list(fields.values()) + [component_id, project_id]

    cursor = conn.execute(
        f"UPDATE components SET {', '.join(set_clauses)} WHERE id = ? AND project_id = ?;",
        values,
    )
    if cursor.rowcount == 0:
        raise NotFoundError("component")

    return get_by_id(conn, component_id, project_id)  # type: ignore


def delete(conn: sqlite3.Connection, component_id: str, project_id: str) -> bool:
    """Delete component (cascades measurements and selections)."""
    cursor = conn.execute(
        "DELETE FROM components WHERE id = ? AND project_id = ?;",
        (component_id, project_id),
    )
    if cursor.rowcount == 0:
        raise NotFoundError("component")
    return True


def delete_unlocked_ai_by_photo(
    conn: sqlite3.Connection, project_id: str, photo_id: str
) -> int:
    """Delete unlocked AI components for a photo (used before inserting new detection run)."""
    cursor = conn.execute(
        """
        DELETE FROM components
        WHERE project_id = ? AND photo_id = ? AND origin = 'ai' AND is_locked = 0;
        """,
        (project_id, photo_id),
    )
    return cursor.rowcount


def count_locked_by_photo(
    conn: sqlite3.Connection, project_id: str, photo_id: str
) -> int:
    """Count all user-protected working components on a photo."""
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM components
        WHERE project_id = ? AND photo_id = ? AND is_locked = 1;
        """,
        (project_id, photo_id),
    )
    return int(cursor.fetchone()[0])


def count_attached_data_for_unlocked_ai(
    conn: sqlite3.Connection, project_id: str, photo_id: str
) -> tuple[int, int]:
    """Count selections and measurements that will cascade on re-detection."""
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*)
             FROM selections s JOIN components c ON c.id = s.component_id
             WHERE c.project_id = ? AND c.photo_id = ?
               AND c.origin = 'ai' AND c.is_locked = 0),
            (SELECT COUNT(*)
             FROM component_measurements m JOIN components c ON c.id = m.component_id
             WHERE c.project_id = ? AND c.photo_id = ?
               AND c.origin = 'ai' AND c.is_locked = 0);
        """,
        (project_id, photo_id, project_id, photo_id),
    ).fetchone()
    return int(row[0]), int(row[1])


def create_detected(
    conn: sqlite3.Connection,
    project_id: str,
    photo_id: str,
    stage_run_id: Optional[str],
    component_type: str,
    label: str,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Insert an immutable normalized, valid detection row."""
    detected_id = generate_id("det")
    now = utc_now()

    conn.execute(
        """
        INSERT INTO detected_components (
            id, project_id, photo_id, stage_run_id, type, label,
            box_x, box_y, box_w, box_h, confidence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            detected_id,
            project_id,
            photo_id,
            stage_run_id,
            component_type,
            label,
            box_x,
            box_y,
            box_w,
            box_h,
            confidence,
            now,
        ),
    )
    cursor = conn.execute(
        "SELECT * FROM detected_components WHERE id = ?;", (detected_id,)
    )
    return dict(cursor.fetchone())


def count_by_project(conn: sqlite3.Connection, project_id: str) -> int:
    """Return count of components in project."""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM components WHERE project_id = ?;", (project_id,)
    )
    return cursor.fetchone()[0]


def count_by_photo(
    conn: sqlite3.Connection, project_id: str, photo_id: str
) -> int:
    """Return working component count for one owned photo."""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM components WHERE project_id = ? AND photo_id = ?;",
        (project_id, photo_id),
    )
    return int(cursor.fetchone()[0])
