"""PDF Report repository."""

import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(
    conn: sqlite3.Connection,
    project_id: str,
    variant_id: Optional[str],
    generation_id: Optional[str],
    pdf_path: str,
    grand_total: float,
    currency: str,
    report_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a generated PDF report."""
    report_id = report_id or generate_id("rep")
    now = utc_now()

    conn.execute(
        """
        INSERT INTO reports (
            id, project_id, variant_id, generation_id, pdf_path,
            grand_total, currency, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            report_id,
            project_id,
            variant_id,
            generation_id,
            pdf_path,
            grand_total,
            currency,
            now,
        ),
    )
    return get_by_id(conn, report_id, project_id)  # type: ignore


def get_by_id(
    conn: sqlite3.Connection, report_id: str, project_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get report by ID."""
    if project_id:
        cursor = conn.execute(
            "SELECT * FROM reports WHERE id = ? AND project_id = ?;",
            (report_id, project_id),
        )
    else:
        cursor = conn.execute("SELECT * FROM reports WHERE id = ?;", (report_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_by_project(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    """List reports for a project ordered by creation time descending."""
    cursor = conn.execute(
        "SELECT * FROM reports WHERE project_id = ? ORDER BY created_at DESC;",
        (project_id,),
    )
    return [dict(row) for row in cursor.fetchall()]
