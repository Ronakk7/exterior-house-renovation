"""FastAPI dependency providers."""

import sqlite3
from functools import lru_cache
from typing import Any, Dict, Generator
from fastapi import Depends, Path as FastApiPath
from app.core.config import Settings
from app.core.database import get_connection
from app.core.errors import NotFoundError
from app.core.logging_setup import get_request_id
from app.core.storage import StorageManager
from app.repositories import project_repo
from app.services.catalogue_service import load_catalogue as load_validated_catalogue

_catalogue_cache: Dict[str, Any] = {}


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


def get_db(settings: Settings = Depends(get_settings)) -> Generator[sqlite3.Connection, None, None]:
    """Yield a per-request SQLite connection and ensure it is closed afterwards."""
    conn = get_connection(settings.DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def get_storage(settings: Settings = Depends(get_settings)) -> StorageManager:
    """Return file storage manager rooted at STORAGE_ROOT."""
    return StorageManager(settings.STORAGE_ROOT)


def load_catalogue(catalogue_path: str) -> Dict[str, Any]:
    """Load and validate catalogue JSON file once at startup."""
    global _catalogue_cache
    _catalogue_cache = load_validated_catalogue(catalogue_path)
    return _catalogue_cache


def get_catalogue() -> Dict[str, Any]:
    """Provide the in-memory loaded catalogue."""
    return _catalogue_cache


def get_project(
    project_id: str = FastApiPath(..., description="Project ID (prj_...)"),
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    """Dependency that resolves and validates project existence from path parameter."""
    proj = project_repo.get_by_id(conn, project_id)
    if not proj:
        raise NotFoundError("project", f"Project '{project_id}' not found.")
    return proj


def get_request_id_dep() -> str:
    """Provide current request ID."""
    return get_request_id()
