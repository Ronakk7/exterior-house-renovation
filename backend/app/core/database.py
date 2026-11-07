"""SQLite database connection, schema setup, pragmas, and transaction helpers."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

from app.core.timeutil import utc_now

SCHEMA_VERSION = "1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    last_step TEXT NOT NULL DEFAULT 'upload' CHECK(last_step IN ('upload', 'components', 'materials', 'redesign', 'estimate', 'report')),
    active_variant_id TEXT NULL,
    floor_count INTEGER NULL CHECK(floor_count IS NULL OR (floor_count >= 1 AND floor_count <= 6)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    view_index INTEGER NOT NULL CHECK(view_index >= 1 AND view_index <= 3),
    facade_label TEXT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    width_px INTEGER NOT NULL,
    height_px INTEGER NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    quality_usable INTEGER NULL CHECK(quality_usable IS NULL OR quality_usable IN (0, 1)),
    quality_reason TEXT NULL,
    detected_at TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, view_index)
);

CREATE TABLE IF NOT EXISTS stage_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('detection', 'redesign', 'ai_estimate', 'report')),
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT NULL,
    duration_ms INTEGER NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS detected_components (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    stage_run_id TEXT NULL,
    type TEXT NOT NULL CHECK(type IN ('wall', 'window', 'door', 'balcony', 'railing', 'pillar', 'parapet', 'gate', 'roof_edge', 'other')),
    label TEXT NOT NULL,
    box_x REAL NOT NULL,
    box_y REAL NOT NULL,
    box_w REAL NOT NULL,
    box_h REAL NOT NULL,
    confidence REAL NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
    FOREIGN KEY (stage_run_id) REFERENCES stage_runs(id) ON DELETE SET NULL,
    CHECK(box_x >= 0 AND box_y >= 0 AND box_w > 0 AND box_h > 0 AND (box_x + box_w) <= 1.002 AND (box_y + box_h) <= 1.002)
);

CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('wall', 'window', 'door', 'balcony', 'railing', 'pillar', 'parapet', 'gate', 'roof_edge', 'other')),
    label TEXT NOT NULL,
    box_x REAL NOT NULL,
    box_y REAL NOT NULL,
    box_w REAL NOT NULL,
    box_h REAL NOT NULL,
    confidence REAL NULL,
    origin TEXT NOT NULL CHECK(origin IN ('ai', 'user')),
    source_detection_id TEXT NULL,
    is_locked INTEGER NOT NULL DEFAULT 0 CHECK(is_locked IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
    FOREIGN KEY (source_detection_id) REFERENCES detected_components(id) ON DELETE SET NULL,
    CHECK(box_x >= 0 AND box_y >= 0 AND box_w > 0 AND box_h > 0 AND (box_x + box_w) <= 1.002 AND (box_y + box_h) <= 1.002)
);

CREATE INDEX IF NOT EXISTS idx_components_project_photo ON components(project_id, photo_id);

CREATE TABLE IF NOT EXISTS variants (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_variants_project_name_nocase
    ON variants(project_id, name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS selections (
    id TEXT PRIMARY KEY,
    variant_id TEXT NOT NULL,
    component_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE,
    FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE,
    UNIQUE(variant_id, component_id)
);

CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    input_fingerprint TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    extra_instructions TEXT NULL,
    model_name TEXT NOT NULL,
    image_path TEXT NULL,
    width_px INTEGER NULL,
    height_px INTEGER NULL,
    is_approved INTEGER NOT NULL DEFAULT 0 CHECK(is_approved IN (0, 1)),
    error_code TEXT NULL,
    error_message TEXT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT NULL,
    duration_ms INTEGER NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS component_measurements (
    id TEXT PRIMARY KEY,
    component_id TEXT NOT NULL UNIQUE,
    input_mode TEXT NOT NULL CHECK(input_mode IN ('dimensions', 'area', 'length')),
    width_ft REAL NULL,
    height_ft REAL NULL,
    length_ft REAL NULL,
    area_sqft REAL NULL,
    deduction_sqft REAL NOT NULL DEFAULT 0 CHECK(deduction_sqft >= 0),
    uncertainty_pct REAL NOT NULL CHECK(uncertainty_pct >= 0 AND uncertainty_pct <= 100),
    source TEXT NOT NULL CHECK(source IN ('user', 'ai_estimate')),
    note TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_rates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    material_rate REAL NULL CHECK(material_rate IS NULL OR material_rate >= 0),
    labour_rate REAL NULL CHECK(labour_rate IS NULL OR labour_rate >= 0),
    wastage_pct REAL NULL CHECK(wastage_pct IS NULL OR (wastage_pct >= 0 AND wastage_pct <= 50)),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, material_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    variant_id TEXT NULL,
    generation_id TEXT NULL,
    pdf_path TEXT NOT NULL,
    grand_total REAL NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE SET NULL,
    FOREIGN KEY (generation_id) REFERENCES generations(id) ON DELETE SET NULL
);
"""


def set_pragmas(conn: sqlite3.Connection) -> None:
    """Set SQLite pragmas on connection."""
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open and configure a SQLite connection."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    set_pragmas(conn)
    return conn


@contextmanager
def transaction(
    conn: sqlite3.Connection, immediate: bool = False
) -> Generator[sqlite3.Connection, None, None]:
    """Provide a transactional scope around a series of operations."""
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables and check or set schema version."""
    with transaction(conn):
        conn.executescript(SCHEMA_SQL)
        cursor = conn.execute("SELECT value FROM app_meta WHERE key = 'schema_version'")
        row = cursor.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
        elif row["value"] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema version mismatch: expected {SCHEMA_VERSION}, found {row['value']}. "
                "Please delete data/app.db to reset for prototype."
            )


def sweep_interrupted_runs(
    conn: sqlite3.Connection, max_timeout_s: int = 150
) -> None:
    """Fail running work only after it exceeds the longest configured AI timeout."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=max_timeout_s)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    finished_at = utc_now()
    with transaction(conn):
        conn.execute(
            """
            UPDATE stage_runs
            SET status = 'failed',
                error_code = 'INTERRUPTED',
                error_message = 'Operation interrupted by server restart.',
                finished_at = ?
            WHERE status = 'running' AND started_at < ?;
            """,
            (finished_at, cutoff),
        )
        conn.execute(
            """
            UPDATE generations
            SET status = 'failed',
                error_code = 'INTERRUPTED',
                error_message = 'Generation interrupted by server restart.',
                completed_at = ?
            WHERE status = 'running' AND created_at < ?;
            """,
            (finished_at, cutoff),
        )
