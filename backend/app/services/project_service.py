"""Project management service."""

import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from app.core.database import transaction
from app.core.storage import StorageManager
from app.repositories import project_repo

logger = logging.getLogger(__name__)


def create_project(
    conn: sqlite3.Connection, storage: StorageManager, name: str
) -> Dict[str, Any]:
    """Create a new project in DB and ensure its storage directory exists."""
    with transaction(conn):
        project = project_repo.create(conn, name)
    storage.ensure_project_dir(project["id"])
    return project


def get_project(conn: sqlite3.Connection, project_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve project metadata with child counts."""
    return project_repo.get_by_id(conn, project_id)


def list_projects(
    conn: sqlite3.Connection, limit: int = 50, offset: int = 0
) -> Tuple[List[Dict[str, Any]], int]:
    """List projects ordered by updated_at descending."""
    return project_repo.list_all(conn, limit=limit, offset=offset)


def update_project(
    conn: sqlite3.Connection, project_id: str, **fields: Any
) -> Dict[str, Any]:
    """Update project details."""
    with transaction(conn):
        return project_repo.update(conn, project_id, **fields)


def delete_project(
    conn: sqlite3.Connection, storage: StorageManager, project_id: str
) -> bool:
    """Delete project from database and remove its entire storage directory."""
    with transaction(conn):
        project_repo.delete(conn, project_id)
    try:
        storage.delete_project_dir(project_id)
    except OSError:
        logger.warning(
            "Could not remove project storage directory",
            extra={"project_id": project_id},
            exc_info=True,
        )
    return True
