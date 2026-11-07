"""Component material selection repository."""

import json
import sqlite3
from typing import Any, Dict, List, Optional
from app.core.errors import NotFoundError
from app.core.ids import generate_id
from app.core.timeutil import utc_now


def upsert(
    conn: sqlite3.Connection,
    variant_id: str,
    component_id: str,
    material_id: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Insert or update a material selection for a component in a variant."""
    now = utc_now()
    params_str = json.dumps(
        params or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    # Check if exists to preserve or create ID
    existing = get(conn, variant_id, component_id)
    if existing:
        conn.execute(
            """
            UPDATE selections
            SET material_id = ?, params_json = ?, updated_at = ?
            WHERE variant_id = ? AND component_id = ?;
            """,
            (material_id, params_str, now, variant_id, component_id),
        )
    else:
        sel_id = generate_id("sel")
        conn.execute(
            """
            INSERT INTO selections (id, variant_id, component_id, material_id, params_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (sel_id, variant_id, component_id, material_id, params_str, now),
        )

    return get(conn, variant_id, component_id)  # type: ignore


def get(
    conn: sqlite3.Connection, variant_id: str, component_id: str
) -> Optional[Dict[str, Any]]:
    """Get selection by variant and component."""
    cursor = conn.execute(
        """
        SELECT component_id, material_id, params_json, updated_at
        FROM selections
        WHERE variant_id = ? AND component_id = ?;
        """,
        (variant_id, component_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json"))
    return d


def list_by_variant(
    conn: sqlite3.Connection, variant_id: str
) -> List[Dict[str, Any]]:
    """List selections for a variant."""
    cursor = conn.execute(
        """
        SELECT s.component_id, s.material_id, s.params_json, s.updated_at
        FROM selections s
        JOIN components c ON c.id = s.component_id
        WHERE s.variant_id = ?
        ORDER BY c.created_at ASC, c.id ASC;
        """,
        (variant_id,),
    )
    results = []
    for row in cursor.fetchall():
        d = dict(row)
        d["params"] = json.loads(d.pop("params_json"))
        results.append(d)
    return results


def copy_variant_selections(
    conn: sqlite3.Connection, source_variant_id: str, target_variant_id: str
) -> None:
    """Copy all selections and their canonical parameter JSON to a new variant."""
    rows = conn.execute(
        """
        SELECT component_id, material_id, params_json
        FROM selections
        WHERE variant_id = ?;
        """,
        (source_variant_id,),
    ).fetchall()
    now = utc_now()
    conn.executemany(
        """
        INSERT INTO selections (
            id, variant_id, component_id, material_id, params_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        [
            (
                generate_id("sel"),
                target_variant_id,
                row["component_id"],
                row["material_id"],
                row["params_json"],
                now,
            )
            for row in rows
        ],
    )


def delete(conn: sqlite3.Connection, variant_id: str, component_id: str) -> bool:
    """Delete a selection."""
    cursor = conn.execute(
        "DELETE FROM selections WHERE variant_id = ? AND component_id = ?;",
        (variant_id, component_id),
    )
    if cursor.rowcount == 0:
        raise NotFoundError("selection")
    return True


def delete_incompatible_for_component(
    conn: sqlite3.Connection, component_id: str, compatible_material_ids: List[str]
) -> int:
    """Delete selections for a component whose material is no longer compatible."""
    if not compatible_material_ids:
        cursor = conn.execute(
            "DELETE FROM selections WHERE component_id = ?;", (component_id,)
        )
        return cursor.rowcount

    placeholders = ",".join("?" for _ in compatible_material_ids)
    cursor = conn.execute(
        f"DELETE FROM selections WHERE component_id = ? AND material_id NOT IN ({placeholders});",
        [component_id] + compatible_material_ids,
    )
    return cursor.rowcount


def count_by_variant(conn: sqlite3.Connection, variant_id: str) -> int:
    """Count selections for a variant."""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM selections WHERE variant_id = ?;", (variant_id,)
    )
    return cursor.fetchone()[0]
