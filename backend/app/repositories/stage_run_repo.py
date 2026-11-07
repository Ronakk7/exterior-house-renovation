"""Stage run execution log repository."""

import json
import sqlite3
from typing import Any, Dict, List, Optional
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def create(conn: sqlite3.Connection, project_id: str, stage: str) -> Dict[str, Any]:
    """Create a new stage run in 'running' state."""
    run_id = generate_id("run")
    now = utc_now()

    conn.execute(
        """
        INSERT INTO stage_runs (
            id, project_id, stage, status, started_at, finished_at,
            duration_ms, error_code, error_message, detail_json
        ) VALUES (?, ?, ?, 'running', ?, NULL, NULL, NULL, NULL, '{}');
        """,
        (run_id, project_id, stage, now),
    )
    return get_by_id(conn, run_id)  # type: ignore


def get_by_id(conn: sqlite3.Connection, run_id: str) -> Optional[Dict[str, Any]]:
    """Get stage run by ID with parsed detail_json."""
    cursor = conn.execute("SELECT * FROM stage_runs WHERE id = ?;", (run_id,))
    row = cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["detail"] = json.loads(d.pop("detail_json", "{}"))
    return d


def list_by_project(
    conn: sqlite3.Connection,
    project_id: str,
    stage: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List stage runs for a project newest first."""
    if stage:
        cursor = conn.execute(
            """
            SELECT * FROM stage_runs
            WHERE project_id = ? AND stage = ?
            ORDER BY started_at DESC, rowid DESC
            LIMIT ?;
            """,
            (project_id, stage, limit),
        )
    else:
        cursor = conn.execute(
            """
            SELECT * FROM stage_runs
            WHERE project_id = ?
            ORDER BY started_at DESC, rowid DESC
            LIMIT ?;
            """,
            (project_id, limit),
        )
    results = []
    for row in cursor.fetchall():
        d = dict(row)
        d["detail"] = json.loads(d.pop("detail_json", "{}"))
        results.append(d)
    return results


def update_completed(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Mark stage run finished."""
    now = utc_now()
    detail_str = json.dumps(detail or {})
    conn.execute(
        """
        UPDATE stage_runs
        SET status = ?,
            error_code = ?,
            error_message = ?,
            detail_json = ?,
            finished_at = ?,
            duration_ms = ?
        WHERE id = ?;
        """,
        (status, error_code, error_message, detail_str, now, duration_ms, run_id),
    )
    return get_by_id(conn, run_id)  # type: ignore
