"""Foundation unit tests covering core infrastructure, database, storage, and repositories."""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings
from app.core.database import get_connection, init_db, sweep_interrupted_runs
from app.core.errors import NotFoundError, ValidationAppError
from app.core.ids import generate_id, generate_request_id
from app.core.storage import StorageManager
from app.core.timeutil import utc_now
from app.repositories import (
    component_repo,
    generation_repo,
    photo_repo,
    project_repo,
    stage_run_repo,
    variant_repo,
)
from app.schemas.common import Box
from app.schemas.projects import ProjectCreate, ProjectUpdate
from pydantic import ValidationError


class TestCoreUtilities(unittest.TestCase):
    """Test IDs, time, and path security."""

    def test_id_generation(self):
        pid = generate_id("prj")
        self.assertTrue(pid.startswith("prj_"))
        self.assertEqual(len(pid), 4 + 16)  # prefix + '_' + 16 hex chars

        req_id = generate_request_id()
        self.assertTrue(req_id.startswith("req_"))
        self.assertEqual(len(req_id), 4 + 12)

    def test_utc_now_format(self):
        now = utc_now()
        self.assertTrue(now.endswith("Z"))
        self.assertIn("T", now)

    def test_box_validation(self):
        # Valid box
        b = Box(x=0.1, y=0.2, w=0.5, h=0.4)
        self.assertEqual(b.x, 0.1)

        # Invalid bounds (exceeding 1.0)
        with self.assertRaises(ValueError):
            Box(x=0.8, y=0.8, w=0.5, h=0.5)

    def test_shared_settings_defaults_validation_and_immutability(self):
        settings = Settings(_env_file=None, AI_MOCK_MODE=True)
        self.assertEqual(settings.DATABASE_PATH, "data/app.db")
        self.assertEqual(settings.STORAGE_ROOT, "storage")
        self.assertEqual(settings.MAX_IMAGE_PIXELS, 40_000_000)
        self.assertEqual(settings.MAX_COMPONENTS_PER_PHOTO, 60)
        self.assertEqual(settings.AI_MOCK_SCENARIO, "ok")
        with self.assertRaises(ValidationError):
            settings.MAX_COMPONENTS_PER_PHOTO = 20

        for field in ("MAX_IMAGE_PIXELS", "MAX_COMPONENTS_PER_PHOTO"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, **{field: 0})

        for scenario in (
            "ok",
            "unusable",
            "no_components",
            "invalid_json",
            "blocked",
            "timeout",
            "rate_limited",
        ):
            with self.subTest(scenario=scenario):
                Settings(
                    _env_file=None,
                    AI_MOCK_MODE=True,
                    AI_MOCK_SCENARIO=scenario,
                )
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                AI_MOCK_MODE=True,
                AI_MOCK_SCENARIO="unknown",
            )

    def test_weeny_data_dir_contains_database_and_storage(self):
        settings = Settings(
            _env_file=None,
            WEENY_DATA_DIR="/data/exterior-renovation",
        )
        self.assertEqual(
            settings.DATABASE_PATH,
            str(Path("/data/exterior-renovation") / "app.db"),
        )
        self.assertEqual(
            settings.STORAGE_ROOT,
            str(Path("/data/exterior-renovation") / "storage"),
        )


class TestStorageManager(unittest.TestCase):
    """Test atomic file operations and directory isolation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = StorageManager(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_atomic_save_and_read(self):
        rel_path = "projects/prj_123/original/photo.jpg"
        content = b"sample image bytes"
        self.storage.save_bytes(rel_path, content)

        read_back = self.storage.read_bytes(rel_path)
        self.assertEqual(read_back, content)

    def test_path_traversal_protection(self):
        with self.assertRaises(ValidationAppError):
            self.storage.save_bytes("../outside.txt", b"danger")

    def test_delete_project_dir(self):
        self.storage.save_bytes("projects/prj_test/original/p.jpg", b"test")
        self.storage.delete_project_dir("prj_test")
        with self.assertRaises(NotFoundError):
            self.storage.read_bytes("projects/prj_test/original/p.jpg")


class TestDatabaseAndRepositories(unittest.TestCase):
    """Test SQLite initialization, pragmas, and repositories."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.conn = get_connection(self.temp_db_path)
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except OSError:
            pass

    def test_all_12_tables_created(self):
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
        tables = {row[0] for row in cursor.fetchall()}
        expected = {
            "app_meta", "projects", "photos", "detected_components",
            "components", "variants", "selections", "generations",
            "component_measurements", "project_rates", "reports", "stage_runs"
        }
        for t in expected:
            self.assertIn(t, tables, f"Expected table '{t}' was not created.")

    def test_project_crud_and_auto_variant(self):
        # Create
        proj = project_repo.create(self.conn, "Villa Renovation")
        self.assertIsNotNone(proj)
        self.assertEqual(proj["name"], "Villa Renovation")
        self.assertEqual(proj["last_step"], "upload")
        self.assertEqual(proj["variant_count"], 1)

        # Get
        fetched = project_repo.get_by_id(self.conn, proj["id"])
        self.assertEqual(fetched["id"], proj["id"])

        # Update
        updated = project_repo.update(self.conn, proj["id"], name="Modern Villa", last_step="components")
        self.assertEqual(updated["name"], "Modern Villa")
        self.assertEqual(updated["last_step"], "components")

        # Delete
        project_repo.delete(self.conn, proj["id"])
        self.assertIsNone(project_repo.get_by_id(self.conn, proj["id"]))

    def test_locked_component_rules(self):
        proj = project_repo.create(self.conn, "House 1")
        # Create photo first to satisfy foreign key
        photo = photo_repo.create(
            self.conn, proj["id"], 1, "test.jpg", "projects/p/original/test.jpg",
            "image/jpeg", 1600, 1200, 100000
        )
        # Create user component
        c_user = component_repo.create(
            self.conn, proj["id"], photo["id"], "wall", "Main Wall",
            0.1, 0.1, 0.5, 0.5, is_locked=1, origin="user"
        )
        self.assertEqual(c_user["is_locked"], 1)

        # Create unlocked AI component
        c_ai = component_repo.create(
            self.conn, proj["id"], photo["id"], "pillar", "Left Pillar",
            0.6, 0.1, 0.1, 0.5, is_locked=0, origin="ai"
        )
        self.assertEqual(c_ai["is_locked"], 0)

        # Simulating re-detection: delete unlocked AI components for that photo
        deleted_count = component_repo.delete_unlocked_ai_by_photo(self.conn, proj["id"], photo["id"])
        self.assertEqual(deleted_count, 1)

        # Locked user component must still exist!
        self.assertIsNotNone(component_repo.get_by_id(self.conn, c_user["id"]))
        # AI component was wiped
        self.assertIsNone(component_repo.get_by_id(self.conn, c_ai["id"]))

    def test_interrupted_run_sweep_preserves_recent_work(self):
        project = project_repo.create(self.conn, "Timeout recovery")
        photo = photo_repo.create(
            self.conn,
            project["id"],
            1,
            "test.jpg",
            "projects/p/original/test.jpg",
            "image/jpeg",
            1600,
            1200,
            100000,
        )
        variant_id = project["active_variant_id"]

        old_run = stage_run_repo.create(self.conn, project["id"], "detection")
        recent_run = stage_run_repo.create(self.conn, project["id"], "detection")
        old_generation = generation_repo.create(
            self.conn,
            project["id"],
            variant_id,
            photo["id"],
            "old",
            "prompt",
            None,
            "model",
        )
        recent_generation = generation_repo.create(
            self.conn,
            project["id"],
            variant_id,
            photo["id"],
            "recent",
            "prompt",
            None,
            "model",
        )

        now = datetime.now(timezone.utc)
        old_timestamp = (now - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute(
            "UPDATE stage_runs SET started_at = ? WHERE id = ?",
            (old_timestamp, old_run["id"]),
        )
        self.conn.execute(
            "UPDATE stage_runs SET started_at = ? WHERE id = ?",
            (recent_timestamp, recent_run["id"]),
        )
        self.conn.execute(
            "UPDATE generations SET created_at = ? WHERE id = ?",
            (old_timestamp, old_generation["id"]),
        )
        self.conn.execute(
            "UPDATE generations SET created_at = ? WHERE id = ?",
            (recent_timestamp, recent_generation["id"]),
        )
        self.conn.commit()

        sweep_interrupted_runs(self.conn, max_timeout_s=60)

        self.assertEqual(
            stage_run_repo.get_by_id(self.conn, old_run["id"])["status"],
            "failed",
        )
        self.assertEqual(
            stage_run_repo.get_by_id(self.conn, recent_run["id"])["status"],
            "running",
        )
        self.assertEqual(
            generation_repo.get_by_id(self.conn, old_generation["id"])["status"],
            "failed",
        )
        self.assertEqual(
            generation_repo.get_by_id(self.conn, recent_generation["id"])["status"],
            "running",
        )


if __name__ == "__main__":
    unittest.main()
