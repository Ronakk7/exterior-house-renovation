"""Project and photo upload tests for Specification 06."""

import io
import os
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.database import get_connection
from app.core.errors import NotFoundError
from app.core.ids import generate_id
from app.core.storage import StorageManager
from app.core.timeutil import utc_now
from app.main import create_app
from app.services.ai.image_prep import prepare_working_image
from app.services.upload_service import upload_photo


class TestProjectUploads(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "app.db")
        self.storage_path = os.path.join(self.temp_dir, "storage")
        self.settings = Settings(
            DATABASE_PATH=self.db_path,
            STORAGE_ROOT=self.storage_path,
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            MAX_UPLOAD_MB=1,
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=10_000,
            MAX_PHOTOS_PER_PROJECT=1,
        )
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def image_bytes(image_format="JPEG", size=(80, 60), exif=None):
        output = io.BytesIO()
        image = Image.new("RGB", size, (120, 80, 40))
        image.save(output, format=image_format, exif=exif or b"")
        return output.getvalue()

    def create_project(self, name="Upload test"):
        response = self.client.post("/api/projects", json={"name": name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def post_photo(self, project_id, data, filename="house.jpg"):
        return self.client.post(
            f"/api/projects/{project_id}/photos",
            files={"file": (filename, data, "application/octet-stream")},
        )

    def test_upload_supported_formats_and_image_retrieval(self):
        for image_format, extension, mime_type in (
            ("JPEG", "jpg", "image/jpeg"),
            ("PNG", "png", "image/png"),
            ("WEBP", "webp", "image/webp"),
        ):
            with self.subTest(image_format=image_format):
                project = self.create_project(image_format)
                image_data = self.image_bytes(image_format)
                response = self.post_photo(project["id"], image_data, f"source.{extension}")
                self.assertEqual(response.status_code, 201, response.text)
                photo = response.json()
                self.assertEqual(photo["mime_type"], mime_type)
                self.assertEqual(photo["width_px"], 80)
                self.assertEqual(photo["height_px"], 60)
                self.assertEqual(photo["file_size_bytes"], len(image_data))
                self.assertIsNone(photo["quality_usable"])
                self.assertNotIn("stored_path", photo)

                listing = self.client.get(f"/api/projects/{project['id']}/photos")
                self.assertEqual(listing.status_code, 200)
                self.assertEqual(listing.json()["items"][0]["id"], photo["id"])
                image_response = self.client.get(photo["image_url"])
                self.assertEqual(image_response.status_code, 200)
                self.assertEqual(image_response.content, image_data)
                self.assertEqual(image_response.headers["content-type"], mime_type)
                self.assertEqual(
                    image_response.headers["cache-control"], "private, max-age=3600"
                )
                self.assertEqual(
                    image_response.headers["x-content-type-options"], "nosniff"
                )

    def test_exif_orientation_dimensions_and_client_filename_sanitization(self):
        exif = Image.Exif()
        exif[274] = 6
        image_data = self.image_bytes("JPEG", size=(80, 40), exif=exif)
        project = self.create_project()
        response = self.post_photo(project["id"], image_data, r"..\secret\house.jpg")
        self.assertEqual(response.status_code, 201, response.text)
        photo = response.json()
        self.assertEqual((photo["width_px"], photo["height_px"]), (40, 80))
        self.assertEqual(photo["original_filename"], "house.jpg")
        original = self.client.get(photo["image_url"]).content
        self.assertEqual(original, image_data)
        working = prepare_working_image(original, self.settings)
        self.assertEqual((working.width_px, working.height_px), (40, 80))
        with Image.open(io.BytesIO(working.bytes)) as working_image:
            self.assertIsNone(working_image.getexif().get(274))

        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT stored_path FROM photos WHERE id = ?", (photo["id"],)
            ).fetchone()
            self.assertNotIn("house.jpg", row["stored_path"])
            self.assertIn(f"{photo['id']}.jpg", row["stored_path"])
        finally:
            conn.close()

    def test_upload_rejects_invalid_size_dimensions_and_format(self):
        project = self.create_project()

        response = self.post_photo(project["id"], b"plain text", "not-an-image.jpg")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "UPLOAD_CORRUPT")

        gif_data = self.image_bytes("GIF")
        response = self.post_photo(project["id"], gif_data, "animated.gif")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["error"]["code"], "UPLOAD_INVALID_TYPE")

        large_image = self.image_bytes("PNG", size=(101, 101))
        response = self.post_photo(project["id"], large_image, "too-many-pixels.png")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "UPLOAD_TOO_LARGE")

        small_image = self.image_bytes("JPEG", size=(20, 31))
        response = self.post_photo(project["id"], small_image, "small.jpg")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "UPLOAD_TOO_SMALL")

        response = self.post_photo(
            project["id"], b"x" * (1024 * 1024 + 1), "oversized.jpg"
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "UPLOAD_TOO_LARGE")

        empty = self.client.post(
            f"/api/projects/{project['id']}/photos",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(empty.json()["error"]["code"], "VALIDATION_ERROR")

    def test_missing_file_and_early_content_length_errors(self):
        project = self.create_project()
        missing = self.client.post(f"/api/projects/{project['id']}/photos")
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(
            missing.json()["error"]["details"]["fields"][0],
            {"field": "file", "problem": "a photo is required"},
        )

        unknown_project = self.client.post(
            "/api/projects/prj_0000000000000000/photos",
            files={"file": ("house.jpg", self.image_bytes(), "image/jpeg")},
            headers={"content-length": str(3 * 1024 * 1024)},
        )
        self.assertEqual(unknown_project.status_code, 404)
        self.assertEqual(
            unknown_project.json()["error"]["details"]["resource"], "project"
        )

        too_large = self.client.post(
            f"/api/projects/{project['id']}/photos",
            files={"file": ("house.jpg", self.image_bytes(), "image/jpeg")},
            headers={"content-length": str(3 * 1024 * 1024)},
        )
        self.assertEqual(too_large.status_code, 413)
        self.assertEqual(too_large.json()["error"]["code"], "UPLOAD_TOO_LARGE")

    def test_project_deletion_removes_photo_storage_and_control_names_are_rejected(self):
        project = self.create_project()
        invalid_name = self.client.post(
            "/api/projects", json={"name": "My\nhouse"}
        )
        self.assertEqual(invalid_name.status_code, 422)

        uploaded = self.post_photo(project["id"], self.image_bytes())
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        project_dir = Path(self.storage_path) / "projects" / project["id"]
        self.assertTrue(project_dir.is_dir())

        deleted = self.client.delete(f"/api/projects/{project['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(project_dir.exists())

    def test_failed_transaction_removes_previously_saved_upload(self):
        conn = get_connection(self.db_path)
        storage = StorageManager(self.storage_path)
        try:
            with self.assertRaises(NotFoundError):
                upload_photo(
                    conn,
                    storage,
                    self.settings,
                    "prj_0000000000000000",
                    io.BytesIO(self.image_bytes()),
                    "house.jpg",
                )
        finally:
            conn.close()
        self.assertEqual(
            list((Path(self.storage_path) / "projects").rglob("*.jpg")), []
        )

    def test_second_photo_is_rejected_without_leaving_a_file(self):
        project = self.create_project()
        first = self.post_photo(project["id"], self.image_bytes())
        self.assertEqual(first.status_code, 201, first.text)

        second = self.post_photo(project["id"], self.image_bytes(), "second.jpg")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "PHOTO_LIMIT_REACHED")

        conn = get_connection(self.db_path)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM photos WHERE project_id = ?",
                    (project["id"],),
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()
        photo_dir = Path(self.storage_path) / "projects" / project["id"] / "original"
        self.assertEqual(len(list(photo_dir.iterdir())), 1)

    def test_concurrent_uploads_cannot_exceed_photo_limit(self):
        project = self.create_project()
        image_data = self.image_bytes()

        def upload():
            return self.post_photo(project["id"], image_data)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _index: upload(), range(2)))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [201, 409],
            [response.text for response in responses],
        )
        errors = [response.json()["error"]["code"] for response in responses if response.status_code != 201]
        self.assertEqual(errors, ["PHOTO_LIMIT_REACHED"])
        conn = get_connection(self.db_path)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM photos WHERE project_id = ?",
                    (project["id"],),
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_photo_delete_cascades_data_but_keeps_reports(self):
        project = self.create_project()
        response = self.post_photo(project["id"], self.image_bytes())
        self.assertEqual(response.status_code, 201, response.text)
        photo = response.json()
        storage = StorageManager(self.storage_path)
        conn = get_connection(self.db_path)
        try:
            variant_id = conn.execute(
                "SELECT id FROM variants WHERE project_id = ?", (project["id"],)
            ).fetchone()["id"]
            component_id = generate_id("cmp")
            generation_id = generate_id("gen")
            report_id = generate_id("rep")
            now = utc_now()
            generated_path = storage.project_path(
                project["id"], "generated", f"{generation_id}.png"
            )
            report_path = storage.project_path(
                project["id"], "reports", f"{report_id}.pdf"
            )
            storage.save_bytes(generated_path, b"generated")
            storage.save_bytes(report_path, b"report")
            with conn:
                conn.execute(
                    """
                    INSERT INTO components (
                        id, project_id, photo_id, type, label, box_x, box_y,
                        box_w, box_h, confidence, origin, source_detection_id,
                        is_locked, created_at, updated_at
                    ) VALUES (?, ?, ?, 'wall', 'front wall', 0, 0, 0.5, 0.5,
                              NULL, 'ai', NULL, 0, ?, ?);
                    """,
                    (component_id, project["id"], photo["id"], now, now),
                )
                conn.execute(
                    """
                    INSERT INTO selections (
                        id, variant_id, component_id, material_id, params_json, updated_at
                    ) VALUES (?, ?, ?, 'paint_emulsion_matte', '{}', ?);
                    """,
                    (generate_id("sel"), variant_id, component_id, now),
                )
                conn.execute(
                    """
                    INSERT INTO component_measurements (
                        id, component_id, input_mode, area_sqft, deduction_sqft,
                        uncertainty_pct, source, created_at, updated_at
                    ) VALUES (?, ?, 'area', 20, 0, 15, 'user', ?, ?);
                    """,
                    (generate_id("mea"), component_id, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO generations (
                        id, project_id, variant_id, photo_id, status, input_fingerprint,
                        prompt_text, model_name, image_path, is_approved, created_at
                    ) VALUES (?, ?, ?, ?, 'succeeded', 'fingerprint', 'prompt',
                              'test-model', ?, 0, ?);
                    """,
                    (
                        generation_id,
                        project["id"],
                        variant_id,
                        photo["id"],
                        generated_path,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO reports (
                        id, project_id, variant_id, generation_id, pdf_path,
                        grand_total, currency, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 'INR', ?);
                    """,
                    (report_id, project["id"], variant_id, generation_id, report_path, now),
                )
        finally:
            conn.close()

        deleted = self.client.delete(
            f"/api/projects/{project['id']}/photos/{photo['id']}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertFalse((Path(self.storage_path) / generated_path).exists())
        self.assertTrue((Path(self.storage_path) / report_path).exists())
        self.assertFalse(
            (Path(self.storage_path) / "projects" / project["id"] / "original" / f"{photo['id']}.jpg").exists()
        )

        conn = get_connection(self.db_path)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM components WHERE photo_id = ?",
                    (photo["id"],),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM component_measurements WHERE component_id = ?",
                    (component_id,),
                ).fetchone()[0],
                0,
            )
            report = conn.execute(
                "SELECT generation_id FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
            self.assertIsNotNone(report)
            self.assertIsNone(report["generation_id"])
        finally:
            conn.close()

    def test_project_patch_navigation_does_not_touch_data_timestamp(self):
        project = self.create_project()
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                "UPDATE projects SET updated_at = '2020-01-01T00:00:00Z' WHERE id = ?",
                (project["id"],),
            )
            conn.commit()
        finally:
            conn.close()
        response = self.client.patch(
            f"/api/projects/{project['id']}", json={"last_step": "components"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_at"], "2020-01-01T00:00:00Z")

        empty_patch = self.client.patch(f"/api/projects/{project['id']}", json={})
        self.assertEqual(empty_patch.status_code, 422)


if __name__ == "__main__":
    unittest.main()
