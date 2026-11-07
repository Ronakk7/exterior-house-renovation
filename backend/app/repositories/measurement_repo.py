"""Component measurement repository."""

import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from app.core.errors import NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def _compute_net_area(row: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to attach derived net_area_sqft to measurement dict."""
    if row.get("area_sqft") is not None:
        deduction = row.get("deduction_sqft") or 0.0
        row["net_area_sqft"] = max(0.0, float(row["area_sqft"]) - float(deduction))
    else:
        row["net_area_sqft"] = None
    return row


def upsert(
    conn: sqlite3.Connection,
    component_id: str,
    input_mode: str,
    source: str = "user",
    width_ft: Optional[float] = None,
    height_ft: Optional[float] = None,
    length_ft: Optional[float] = None,
    area_sqft: Optional[float] = None,
    deduction_sqft: float = 0.0,
    uncertainty_pct: float = 15.0,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert or update a measurement for a component."""
    now = utc_now()

    # Enforce field nullability based on input_mode per spec 01 §4.9
    if input_mode == "dimensions":
        calc_area = float(
            (Decimal(str(width_ft or 0)) * Decimal(str(height_ft or 0))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        final_width = width_ft
        final_height = height_ft
        final_length = None
        final_area = calc_area
    elif input_mode == "area":
        final_width = None
        final_height = None
        final_length = None
        final_area = area_sqft
    elif input_mode == "length":
        final_width = None
        final_height = None
        final_length = length_ft
        final_area = None
    else:
        raise ValueError(f"Unknown input_mode: {input_mode}")

    existing = get_by_component(conn, component_id)
    if existing:
        conn.execute(
            """
            UPDATE component_measurements
            SET input_mode = ?, width_ft = ?, height_ft = ?, length_ft = ?,
                area_sqft = ?, deduction_sqft = ?, uncertainty_pct = ?,
                source = ?, note = ?, updated_at = ?
            WHERE component_id = ?;
            """,
            (
                input_mode,
                final_width,
                final_height,
                final_length,
                final_area,
                deduction_sqft,
                uncertainty_pct,
                source,
                note,
                now,
                component_id,
            ),
        )
    else:
        mea_id = generate_id("mea")
        conn.execute(
            """
            INSERT INTO component_measurements (
                id, component_id, input_mode, width_ft, height_ft, length_ft,
                area_sqft, deduction_sqft, uncertainty_pct, source, note,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                mea_id,
                component_id,
                input_mode,
                final_width,
                final_height,
                final_length,
                final_area,
                deduction_sqft,
                uncertainty_pct,
                source,
                note,
                now,
                now,
            ),
        )

    return get_by_component(conn, component_id)  # type: ignore


def get_by_component(
    conn: sqlite3.Connection, component_id: str
) -> Optional[Dict[str, Any]]:
    """Get measurement for a component."""
    cursor = conn.execute(
        """
        SELECT component_id, input_mode, width_ft, height_ft, length_ft,
               area_sqft, deduction_sqft, uncertainty_pct, source, note, updated_at
        FROM component_measurements
        WHERE component_id = ?;
        """,
        (component_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return _compute_net_area(dict(row))


def list_by_project(conn: sqlite3.Connection, project_id: str) -> List[Dict[str, Any]]:
    """List measurements for all components of a project."""
    cursor = conn.execute(
        """
        SELECT m.component_id, m.input_mode, m.width_ft, m.height_ft, m.length_ft,
               m.area_sqft, m.deduction_sqft, m.uncertainty_pct, m.source, m.note, m.updated_at
        FROM component_measurements m
        JOIN components c ON m.component_id = c.id
        WHERE c.project_id = ?
        ORDER BY c.created_at ASC, c.id ASC;
        """,
        (project_id,),
    )
    return [_compute_net_area(dict(row)) for row in cursor.fetchall()]


def delete(conn: sqlite3.Connection, component_id: str) -> bool:
    """Delete measurement for a component."""
    cursor = conn.execute(
        "DELETE FROM component_measurements WHERE component_id = ?;", (component_id,)
    )
    if cursor.rowcount == 0:
        raise NotFoundError("measurement")
    return True


def delete_ai_estimates_for_component(
    conn: sqlite3.Connection, component_id: str
) -> bool:
    """Delete measurement only if its source is 'ai_estimate' (used on component box edit)."""
    cursor = conn.execute(
        "DELETE FROM component_measurements WHERE component_id = ? AND source = 'ai_estimate';",
        (component_id,),
    )
    return cursor.rowcount > 0
