"""File storage helper with path traversal protection and atomic writes."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Union

from app.core.errors import NotFoundError, ValidationAppError


class StorageManager:
    """Manages file storage rooted at storage_root."""

    def __init__(self, storage_root: Union[str, Path]) -> None:
        self.root = Path(storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, relative_path: str) -> Path:
        """Resolve path and ensure it remains strictly inside storage_root."""
        # Normalize forward slashes and strip leading slashes
        clean_rel = relative_path.replace("\\", "/").lstrip("/")
        target = (self.root / clean_rel).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise ValidationAppError("Path traversal detected or invalid storage path.")
        return target

    def save_bytes(self, relative_path: str, data: bytes) -> None:
        """Save bytes atomically using a temporary file and rename."""
        target_path = self._resolve_safe_path(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_fd, temp_path = tempfile.mkstemp(
            dir=str(target_path.parent), prefix="tmp_upload_"
        )
        try:
            with os.fdopen(temp_fd, "wb") as f:
                f.write(data)
            # Atomic rename (on Windows, os.replace replaces existing file)
            os.replace(temp_path, str(target_path))
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def read_bytes(self, relative_path: str) -> bytes:
        """Read bytes from storage, raising NotFoundError if missing."""
        target_path = self._resolve_safe_path(relative_path)
        if not target_path.is_file():
            raise NotFoundError("file", "Stored file not found.")
        return target_path.read_bytes()

    def get_file_path(self, relative_path: str) -> Path:
        """Return resolved path if file exists, else raise NotFoundError."""
        target_path = self._resolve_safe_path(relative_path)
        if not target_path.is_file():
            raise NotFoundError("file", "Stored file not found.")
        return target_path

    def delete_file(self, relative_path: str) -> None:
        """Delete a file if it exists; ignore if missing."""
        try:
            target_path = self._resolve_safe_path(relative_path)
            if target_path.is_file():
                target_path.unlink()
        except FileNotFoundError:
            return

    def delete_project_dir(self, project_id: str) -> None:
        """Recursively delete the projects/{project_id} directory."""
        project_dir = self._resolve_safe_path(f"projects/{project_id}")
        if project_dir.is_dir():
            shutil.rmtree(str(project_dir))

    def project_path(self, project_id: str, kind: str, filename: str) -> str:
        """Build a relative storage path with forward slashes."""
        if kind not in ("original", "generated", "reports"):
            raise ValueError(f"Invalid storage kind: {kind}")
        return f"projects/{project_id}/{kind}/{filename}"

    def ensure_project_dir(self, project_id: str) -> None:
        """Create a project's storage directory after its database row is committed."""
        self._resolve_safe_path(f"projects/{project_id}").mkdir(
            parents=True, exist_ok=True
        )
