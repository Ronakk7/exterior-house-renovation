"""Project material rate overrides repository."""

import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def upsert(
    conn: sqlite3.Connection,
    project_id: str,
    material_id: str,
    material_rate: Optional[float] = None,
    labour_rate: Optional[float] = None,
    wastage_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Insert or update rate override for a material in a project."""
    now = utc_now()
    existing = get_by_material(conn, project_id, material_id)
    if existing:
        conn.execute(
            """
            UPDATE project_rates
            SET material_rate = ?, labour_rate = ?, wastage_pct = ?, updated_at = ?
            WHERE project_id = ? AND material_id = ?;
            """,
            (material_rate, labour_rate, wastage_pct, now, project_id, material_id),
        )
    else:
        rate_id = generate_id("rat")
        conn.execute(
            """
            INSERT INTO project_rates (
                id, project_id, material_id, material_rate, labour_rate, wastage_pct, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                rate_id,
                project_id,
                material_id,
                material_rate,
                labour_rate,
                wastage_pct,
                now,
            ),
        )

    return get_by_material(conn, project_id, material_id)  # type: ignore


def get_by_material(
    conn: sqlite3.Connection, project_id: str, material_id: str
) -> Optional[Dict[str, Any]]:
    """Get project rate override for a material."""
    cursor = conn.execute(
        """
        SELECT material_id, material_rate, labour_rate, wastage_pct, updated_at
        FROM project_rates
        WHERE project_id = ? AND material_id = ?;
        """,
        (project_id, material_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_by_project(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    """List all rate overrides for a project."""
    cursor = conn.execute(
        """
        SELECT material_id, material_rate, labour_rate, wastage_pct, updated_at
        FROM project_rates
        WHERE project_id = ?;
        """,
        (project_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def delete(conn: sqlite3.Connection, project_id: str, material_id: str) -> bool:
    """Reset material rate override to defaults (deletes the row)."""
    cursor = conn.execute(
        "DELETE FROM project_rates WHERE project_id = ? AND material_id = ?;",
        (project_id, material_id),
    )
    if cursor.rowcount == 0:
        raise NotFoundError("rate_override")
    return True

