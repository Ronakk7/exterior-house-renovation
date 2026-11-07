"""Report model, PDF lifecycle, and download endpoint tests."""

import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_catalogue, get_settings
from app.core.config import Settings
from app.core.database import get_connection
from app.core.storage import StorageManager
from app.main import create_app
from app.repositories import generation_repo
from app.repositories import variant_repo
from app.services.pdf_renderer import (
    _prepared_image,
    _region_map,
    format_currency,
    project_slug,
    render_report_pdf,
    sanitize_pdf_text,
)
from app.services.report_service import build_report_model


class TestReportFormatting(unittest.TestCase):
    def test_inr_formatting_and_latin1_sanitation(self):
        self.assertEqual(format_currency(107510, "INR"), "INR 1,07,510.00")
        self.assertEqual(format_currency(0.5, "INR"), "INR 0.50")
        self.assertEqual(sanitize_pdf_text("Café 🏠"), "Café ?")

    def test_project_slug(self):
        self.assertEqual(project_slug("My House #1!"), "my-house-1")
        self.assertEqual(project_slug(" !!! "), "project")
        self.assertLessEqual(len(project_slug("a " * 100)), 40)


class TestReportAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.settings = Settings(
            _env_file=None,
            DATABASE_PATH=str(Path(self.temp_dir) / "app.db"),
            STORAGE_ROOT=str(Path(self.temp_dir) / "storage"),
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=1_000_000,
        )
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        created = self.client.post("/api/projects", json={"name": "My House #1!"})
        self.assertEqual(created.status_code, 201, created.text)
        self.project = created.json()
        self.project_id = self.project["id"]
        image = io.BytesIO()
        Image.new("RGB", (640, 480), (110, 125, 135)).save(image, format="JPEG")
        uploaded = self.client.post(
            f"/api/projects/{self.project_id}/photos",
            files={"file": ("house.jpg", image.getvalue(), "image/jpeg")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self.photo = uploaded.json()
        created_component = self.client.post(
            f"/api/projects/{self.project_id}/components",
            json={
                "photo_id": self.photo["id"],
                "type": "wall",
                "label": "Front façade",
                "box": {"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.7},
            },
        )
        self.assertEqual(created_component.status_code, 201, created_component.text)
        self.component = created_component.json()
        self.variant_id = self.project["active_variant_id"]
        selected = self.client.put(
            f"/api/projects/{self.project_id}/variants/{self.variant_id}/selections/{self.component['id']}",
            json={
                "material_id": "paint_emulsion_matte",
                "params": {"color_hex": "#F5F0E8", "note": "Check sample"},
            },
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        measured = self.client.put(
            f"/api/projects/{self.project_id}/components/{self.component['id']}/measurement",
            json={"input_mode": "dimensions", "width_ft": 20, "height_ft": 10},
        )
        self.assertEqual(measured.status_code, 200, measured.text)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_report(self, body=None):
        return self.client.post(
            f"/api/projects/{self.project_id}/reports",
            json=body or {"variant_id": self.variant_id},
        )

    def _generation(self, variant_id=None, status="succeeded", approved=False):
        connection = get_connection(self.settings.DATABASE_PATH)
        storage = StorageManager(self.settings.STORAGE_ROOT)
        path = storage.project_path(self.project_id, "generated", "report-test.png")
        png = io.BytesIO()
        Image.new("RGB", (320, 240), (30, 80, 110)).save(png, format="PNG")
        storage.save_bytes(path, png.getvalue())
        try:
            generation = generation_repo.create(
                connection,
                self.project_id,
                variant_id or self.variant_id,
                self.photo["id"],
                "outdated-fingerprint",
                "prompt",
                None,
                "mock",
            )
            generation_repo.update_completed(
                connection,
                generation["id"],
                status,
                image_path=path if status == "succeeded" else None,
                width_px=320 if status == "succeeded" else None,
                height_px=240 if status == "succeeded" else None,
            )
            if approved:
                generation_repo.update_approval(
                    connection, generation["id"], self.project_id, True
                )
            connection.commit()
            return generation["id"]
        finally:
            connection.close()

    def test_pdf_generation_download_history_and_project_cleanup(self):
        estimate = self.client.get(
            f"/api/projects/{self.project_id}/variants/{self.variant_id}/estimate"
        ).json()
        response = self._create_report()
        self.assertEqual(response.status_code, 201, response.text)
        report = response.json()
        self.assertEqual(report["grand_total"], estimate["grand_total"])
        self.assertTrue(report["download_url"].endswith(f"/reports/{report['id']}/download"))
        downloaded = self.client.get(report["download_url"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers["content-type"], "application/pdf")
        self.assertIn('filename="renovation-report-my-house-1.pdf"', downloaded.headers["content-disposition"])
        self.assertTrue(downloaded.content.startswith(b"%PDF-"))
        page_count = re.search(rb"/Count\s+(\d+)", downloaded.content)
        self.assertIsNotNone(page_count)
        self.assertGreaterEqual(int(page_count.group(1)), 3)
        self.assertIn(b"My House #1!", downloaded.content)
        self.assertRegex(downloaded.content, rb"Page 1 of [0-9]+")
        self.assertIn(b"No redesigned image was generated", downloaded.content)

        second = self._create_report()
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(report["id"], second.json()["id"])
        listed = self.client.get(f"/api/projects/{self.project_id}/reports")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["items"]), 2)

        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            stored = conn.execute(
                "SELECT pdf_path FROM reports WHERE id = ?", (report["id"],)
            ).fetchone()
        finally:
            conn.close()
        report_path = Path(self.settings.STORAGE_ROOT) / stored["pdf_path"]
        self.assertTrue(report_path.is_file())
        removed = self.client.delete(f"/api/projects/{self.project_id}")
        self.assertEqual(removed.status_code, 204)
        self.assertFalse(report_path.exists())

    def test_model_includes_missing_measurement_and_no_redesign_placeholder(self):
        self.client.delete(
            f"/api/projects/{self.project_id}/components/{self.component['id']}/measurement"
        )
        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            variant = variant_repo.get_by_id(conn, self.variant_id, self.project_id)
            model = build_report_model(
                conn,
                StorageManager(self.settings.STORAGE_ROOT),
                self.project_id,
                "rep_model",
                variant,
                None,
                get_catalogue(),
                "INR",
            )
        finally:
            conn.close()
        self.assertEqual(model["redesign"]["status"], "none")
        self.assertIn("No redesigned image", model["redesign"]["status_text"])
        self.assertEqual(model["missing_measurements"][0]["component_id"], self.component["id"])
        self.assertEqual(model["summary"]["missing_measurements"], 1)
        response = self._create_report()
        self.assertEqual(response.status_code, 201, response.text)
        report_id = response.json()["id"]
        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            row = conn.execute("SELECT grand_total FROM reports WHERE id = ?", (report_id,)).fetchone()
            self.assertEqual(row["grand_total"], 0)
            stage = conn.execute(
                "SELECT status FROM stage_runs WHERE project_id = ? AND stage = 'report' ORDER BY started_at DESC LIMIT 1",
                (self.project_id,),
            ).fetchone()
            self.assertEqual(stage["status"], "succeeded")
        finally:
            conn.close()

    def test_stale_generation_and_explicit_failed_generation(self):
        stale_id = self._generation(approved=True)
        from app.services.pdf_renderer import render_report_pdf
        captured = {}

        def capture_model(model, storage):
            captured.update(model)
            return render_report_pdf(model, storage)

        with patch("app.services.report_service.render_report_pdf", side_effect=capture_model):
            response = self._create_report({"variant_id": self.variant_id, "generation_id": stale_id})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(captured["redesign"]["status"], "outdated")
        self.assertIn("OUTDATED", captured["redesign"]["status_text"])
        failed_id = self._generation(status="failed")
        failed = self._create_report({"variant_id": self.variant_id, "generation_id": failed_id})
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(failed.json()["error"]["details"]["reason"], "generation_not_succeeded")

    def test_ai_measurement_source_is_reported_without_ai_calls(self):
        self.client.delete(
            f"/api/projects/{self.project_id}/components/{self.component['id']}/measurement"
        )
        with patch("app.services.ai.mock.time.sleep"):
            estimate_result = self.client.post(
                f"/api/projects/{self.project_id}/measurements/ai-estimate",
                json={"component_ids": [self.component["id"]]},
            )
        self.assertEqual(estimate_result.status_code, 200, estimate_result.text)
        self.assertEqual(estimate_result.json()["items"][0]["source"], "ai_estimate")

        from app.services.pdf_renderer import render_report_pdf
        captured = {}

        def capture_model(model, storage):
            captured.update(model)
            return render_report_pdf(model, storage)

        with patch("app.services.measurement_service.get_vision_client", side_effect=AssertionError("report called AI")), \
             patch("app.services.redesign_service.get_image_client", side_effect=AssertionError("report called AI")), \
             patch("app.services.report_service.render_report_pdf", side_effect=capture_model):
            response = self._create_report()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(captured["summary"]["ai_measurements"], 1)
        self.assertEqual(captured["quantities"][0]["measurement_source"], "ai_estimate")
        self.assertTrue(any("may be inaccurate by 25% or more" in note for note in captured["limitations"]))

    def test_large_photo_is_downscaled_and_region_map_handles_twelve_regions(self):
        conn = get_connection(self.settings.DATABASE_PATH)
        storage = StorageManager(self.settings.STORAGE_ROOT)
        try:
            variant = variant_repo.get_by_id(conn, self.variant_id, self.project_id)
            model = build_report_model(
                conn,
                storage,
                self.project_id,
                "rep_large",
                variant,
                None,
                get_catalogue(),
                "INR",
            )
        finally:
            conn.close()
        large_photo = io.BytesIO()
        Image.new("RGB", (4000, 3000), (110, 125, 135)).save(
            large_photo, format="JPEG", quality=90
        )
        large_path = storage.project_path(self.project_id, "original", "large-test.jpg")
        storage.save_bytes(large_path, large_photo.getvalue())
        model["photos"].update({
            "original_path": large_path,
            "width_px": 4000,
            "height_px": 3000,
        })
        prepared = _prepared_image(storage, large_path, 1600)
        with Image.open(io.BytesIO(prepared)) as image:
            self.assertEqual(image.size, (1600, 1200))
        regions = [
            {
                "number": index,
                "type": "wall",
                "box_x": (index - 1) / 12,
                "box_y": 0.1,
                "box_w": 0.06,
                "box_h": 0.4,
            }
            for index in range(1, 13)
        ]
        region_map = _region_map(prepared, regions, 1600)
        with Image.open(io.BytesIO(region_map)) as image:
            self.assertEqual(image.size, (1600, 1200))
        pdf = render_report_pdf(model, storage)
        self.assertLess(len(pdf), 8 * 1024 * 1024)

    def test_generation_from_another_variant_is_not_found(self):
        other = self.client.post(
            f"/api/projects/{self.project_id}/variants",
            json={"name": "Second design"},
        )
        self.assertEqual(other.status_code, 201, other.text)
        other_variant = other.json()["id"]
        self.client.put(
            f"/api/projects/{self.project_id}/variants/{other_variant}/selections/{self.component['id']}",
            json={"material_id": "paint_emulsion_matte", "params": {}},
        )
        generation_id = self._generation()
        response = self._create_report({
            "variant_id": other_variant,
            "generation_id": generation_id,
        })
        self.assertEqual(response.status_code, 404)

    def test_missing_redesign_file_is_treated_as_no_image(self):
        generation_id = self._generation()
        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            row = conn.execute(
                "SELECT image_path FROM generations WHERE id = ?", (generation_id,)
            ).fetchone()
        finally:
            conn.close()
        StorageManager(self.settings.STORAGE_ROOT).delete_file(row["image_path"])
        response = self._create_report({
            "variant_id": self.variant_id,
            "generation_id": generation_id,
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIsNone(response.json()["generation_id"])

    def test_missing_original_photo_fails_without_partial_report(self):
        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            row = conn.execute(
                "SELECT stored_path FROM photos WHERE id = ?", (self.photo["id"],)
            ).fetchone()
        finally:
            conn.close()
        StorageManager(self.settings.STORAGE_ROOT).delete_file(row["stored_path"])
        response = self._create_report()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.project_id}/reports").json()["items"],
            [],
        )

    def test_mock_upload_to_report_workflow(self):
        from unittest.mock import patch

        with patch("app.services.ai.mock.time.sleep"):
            detected = self.client.post(
                f"/api/projects/{self.project_id}/photos/{self.photo['id']}/detect"
            )
        self.assertEqual(detected.status_code, 200, detected.text)
        self.assertTrue(detected.json()["usable"])

        edited = self.client.patch(
            f"/api/projects/{self.project_id}/components/{self.component['id']}",
            json={
                "label": "Edited front wall",
                "box": {"x": 0.12, "y": 0.1, "w": 0.58, "h": 0.7},
            },
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        created_variant = self.client.post(
            f"/api/projects/{self.project_id}/variants",
            json={"name": "E2E design", "copy_from_variant_id": self.variant_id},
        )
        self.assertEqual(created_variant.status_code, 201, created_variant.text)
        variant_id = created_variant.json()["id"]
        activated = self.client.patch(
            f"/api/projects/{self.project_id}",
            json={"active_variant_id": variant_id},
        )
        self.assertEqual(activated.status_code, 200, activated.text)

        with patch("app.services.ai.mock.time.sleep"):
            generated = self.client.post(
                f"/api/projects/{self.project_id}/variants/{variant_id}/generations",
                json={"photo_id": self.photo["id"]},
            )
        self.assertEqual(generated.status_code, 201, generated.text)
        generation_id = generated.json()["id"]
        approved = self.client.patch(
            f"/api/projects/{self.project_id}/generations/{generation_id}",
            json={"is_approved": True},
        )
        self.assertEqual(approved.status_code, 200, approved.text)

        measurement = self.client.put(
            f"/api/projects/{self.project_id}/components/{self.component['id']}/measurement",
            json={"input_mode": "dimensions", "width_ft": 22, "height_ft": 11},
        )
        self.assertEqual(measurement.status_code, 200, measurement.text)
        estimate = self.client.get(
            f"/api/projects/{self.project_id}/variants/{variant_id}/estimate"
        )
        self.assertEqual(estimate.status_code, 200, estimate.text)
        self.assertEqual(len(estimate.json()["line_items"]), 1)

        report = self._create_report({
            "variant_id": variant_id,
            "generation_id": generation_id,
        })
        self.assertEqual(report.status_code, 201, report.text)
        self.assertEqual(report.json()["grand_total"], estimate.json()["grand_total"])
        self.assertEqual(
            self.client.get(report.json()["download_url"]).status_code,
            200,
        )

    def test_end_to_end_upload_detection_edit_selection_redesign_estimate_report(self):
        from unittest.mock import patch

        created = self.client.post(
            "/api/projects",
            json={"name": "Complete mock workflow"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()
        project_id = project["id"]

        image = io.BytesIO()
        Image.new("RGB", (640, 480), (110, 125, 135)).save(image, format="JPEG")
        uploaded = self.client.post(
            f"/api/projects/{project_id}/photos",
            files={"file": ("workflow.jpg", image.getvalue(), "image/jpeg")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        photo = uploaded.json()

        with patch("app.services.ai.mock.time.sleep"):
            detected = self.client.post(
                f"/api/projects/{project_id}/photos/{photo['id']}/detect"
            )
        self.assertEqual(detected.status_code, 200, detected.text)
        component = next(
            item
            for item in detected.json()["components"]
            if item["type"] == "wall" and item["supported"]
        )
        corrected = self.client.patch(
            f"/api/projects/{project_id}/components/{component['id']}",
            json={"label": "Owner-corrected front wall"},
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertTrue(corrected.json()["component"]["is_locked"])
        with patch("app.services.ai.mock.time.sleep"):
            redetected = self.client.post(
                f"/api/projects/{project_id}/photos/{photo['id']}/detect"
            )
        preserved = next(
            item
            for item in redetected.json()["components"]
            if item["id"] == component["id"]
        )
        self.assertEqual(preserved["label"], "Owner-corrected front wall")
        self.assertTrue(preserved["is_locked"])

        variant_id = project["active_variant_id"]
        selected = self.client.put(
            f"/api/projects/{project_id}/variants/{variant_id}/selections/{component['id']}",
            json={"material_id": "paint_emulsion_matte", "params": {}},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        with patch("app.services.ai.mock.time.sleep"):
            generated = self.client.post(
                f"/api/projects/{project_id}/variants/{variant_id}/generations",
                json={"photo_id": photo["id"]},
            )
        self.assertEqual(generated.status_code, 201, generated.text)
        self.assertEqual(generated.json()["status"], "succeeded")

        measured = self.client.put(
            f"/api/projects/{project_id}/components/{component['id']}/measurement",
            json={"input_mode": "dimensions", "width_ft": 20, "height_ft": 10},
        )
        self.assertEqual(measured.status_code, 200, measured.text)
        estimate = self.client.get(
            f"/api/projects/{project_id}/variants/{variant_id}/estimate"
        )
        self.assertEqual(estimate.status_code, 200, estimate.text)
        self.assertEqual(len(estimate.json()["line_items"]), 1)

        report = self.client.post(
            f"/api/projects/{project_id}/reports",
            json={
                "variant_id": variant_id,
                "generation_id": generated.json()["id"],
            },
        )
        self.assertEqual(report.status_code, 201, report.text)
        self.assertEqual(report.json()["grand_total"], estimate.json()["grand_total"])
        download = self.client.get(report.json()["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["content-type"], "application/pdf")

    def test_no_selections_and_unknown_download(self):
        second = self.client.post(
            f"/api/projects/{self.project_id}/variants",
            json={"name": "Empty design"},
        )
        response = self._create_report({"variant_id": second.json()["id"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "NO_SELECTIONS")
        unknown = self.client.get(
            f"/api/projects/{self.project_id}/reports/rep_unknown/download"
        )
        self.assertEqual(unknown.status_code, 404)

    def test_render_failure_leaves_no_report_file_or_row_and_fails_stage(self):
        with patch(
            "app.services.report_service.render_report_pdf",
            side_effect=RuntimeError("test renderer failure"),
        ):
            response = self._create_report()
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.project_id}/reports").json()["items"],
            [],
        )
        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            run = conn.execute(
                "SELECT status, error_code FROM stage_runs WHERE project_id = ? AND stage = 'report' ORDER BY started_at DESC LIMIT 1",
                (self.project_id,),
            ).fetchone()
            self.assertEqual((run["status"], run["error_code"]), ("failed", "INTERNAL_ERROR"))
            files = list((Path(self.settings.STORAGE_ROOT) / "projects" / self.project_id / "reports").glob("*.pdf"))
            self.assertEqual(files, [])
        finally:
            conn.close()
