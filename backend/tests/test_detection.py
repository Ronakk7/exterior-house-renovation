"""Component detection API and persistence tests."""

import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.database import get_connection, transaction
from app.core.storage import StorageManager
from app.main import create_app
from app.repositories import component_repo, photo_repo, project_repo, stage_run_repo
from app.services import detection_service
from app.services.ai.vision import VisionResult


class TestDetection(unittest.TestCase):
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
            AI_MOCK_SCENARIO="ok",
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=100_000,
            MAX_COMPONENTS_PER_PHOTO=60,
        )
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        project = self.client.post("/api/projects", json={"name": "Detection test"})
        self.assertEqual(project.status_code, 201, project.text)
        self.project = project.json()
        upload = self.client.post(
            f"/api/projects/{self.project['id']}/photos",
            files={"file": ("house.jpg", self.image_bytes(), "image/jpeg")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        self.photo = upload.json()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def image_bytes():
        output = io.BytesIO()
        Image.new("RGB", (160, 120), (120, 80, 40)).save(output, format="JPEG")
        return output.getvalue()

    @staticmethod
    def rendering_bytes():
        image = Image.new("RGB", (160, 120), (150, 195, 220))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        draw.polygon([(25, 50), (80, 20), (135, 50)], fill=(75, 65, 60))
        draw.rectangle((35, 48, 125, 108), fill=(220, 205, 175))
        draw.rectangle((48, 65, 68, 84), fill=(90, 150, 180))
        draw.rectangle((90, 65, 110, 84), fill=(90, 150, 180))
        draw.rectangle((72, 78, 88, 108), fill=(105, 75, 55))
        draw.rectangle((20, 108, 140, 116), fill=(95, 125, 75))
        output = io.BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()

    def detect(self):
        return self.client.post(
            f"/api/projects/{self.project['id']}/photos/{self.photo['id']}/detect"
        )

    def connect(self):
        return get_connection(self.db_path)

    def test_mock_detection_persists_normalized_components_and_stage_detail(self):
        with patch("app.services.ai.mock.time.sleep"):
            response = self.detect()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["usable"])
        self.assertEqual(len(result["components"]), 11)
        self.assertTrue(all(0 <= c["box"]["x"] <= 1 for c in result["components"]))
        self.assertTrue(all(c["origin"] == "ai" and not c["is_locked"] for c in result["components"]))
        self.assertTrue(all("supported" in c for c in result["components"]))

        conn = self.connect()
        try:
            detections = conn.execute(
                "SELECT COUNT(*) FROM detected_components WHERE photo_id = ?",
                (self.photo["id"],),
            ).fetchone()[0]
            self.assertEqual(detections, 11)
            run = stage_run_repo.get_by_id(conn, result["stage_run_id"])
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(run["detail"]["inserted"], 11)
            self.assertEqual(run["detail"]["prompt_version"], "det-v2")
            self.assertNotIn("raw_response", run["detail"])
        finally:
            conn.close()

    def test_photo_and_rendered_exteriors_continue_through_selection_and_estimate(self):
        class FakeVision:
            def __init__(self):
                self.instructions = []
                self.versions = []

            def analyze_image(self, image, instructions, schema, prompt_version):
                self.instructions.append(instructions)
                self.versions.append(prompt_version)
                return VisionResult(
                    data=SimpleNamespace(
                        usable=True,
                        quality_reason=None,
                        components=[
                            {
                                "type": "wall",
                                "label": "main front wall",
                                "box_2d": [100, 100, 900, 900],
                                "confidence": 0.95,
                            }
                        ],
                    ),
                    attempts=1,
                    duration_ms=1,
                    model_name="mock-vision",
                    raw_text_excerpt="{}",
                )

        fake_vision = FakeVision()
        for label, image_bytes in (
            ("photograph", self.image_bytes()),
            ("rendering", self.rendering_bytes()),
        ):
            with self.subTest(image_type=label):
                project_response = self.client.post(
                    "/api/projects", json={"name": f"{label} workflow"}
                )
                self.assertEqual(project_response.status_code, 201)
                project = project_response.json()
                upload = self.client.post(
                    f"/api/projects/{project['id']}/photos",
                    files={"file": (f"{label}.jpg", image_bytes, "image/jpeg")},
                )
                self.assertEqual(upload.status_code, 201, upload.text)
                photo = upload.json()

                with patch(
                    "app.services.detection_service.get_vision_client",
                    return_value=fake_vision,
                ):
                    detected = self.client.post(
                        f"/api/projects/{project['id']}/photos/{photo['id']}/detect"
                    )
                self.assertEqual(detected.status_code, 200, detected.text)
                self.assertTrue(detected.json()["usable"])
                self.assertEqual(len(detected.json()["components"]), 1)

                components = self.client.get(
                    f"/api/projects/{project['id']}/components?photo_id={photo['id']}"
                )
                self.assertEqual(components.status_code, 200, components.text)
                component = components.json()["items"][0]
                selection = self.client.put(
                    f"/api/projects/{project['id']}/variants/"
                    f"{project['active_variant_id']}/selections/{component['id']}",
                    json={"material_id": "paint_emulsion_matte", "params": {}},
                )
                self.assertEqual(selection.status_code, 200, selection.text)
                measurement = self.client.put(
                    f"/api/projects/{project['id']}/components/{component['id']}/measurement",
                    json={"input_mode": "dimensions", "width_ft": 20, "height_ft": 10},
                )
                self.assertEqual(measurement.status_code, 200, measurement.text)
                estimate = self.client.get(
                    f"/api/projects/{project['id']}/variants/"
                    f"{project['active_variant_id']}/estimate"
                )
                self.assertEqual(estimate.status_code, 200, estimate.text)
                self.assertEqual(len(estimate.json()["line_items"]), 1)

        self.assertEqual(fake_vision.versions, ["det-v2", "det-v2"])
        self.assertTrue(
            all(
                "3D architectural renderings" in prompt
                and "Do not reject it because it is not a real photograph." in prompt
                for prompt in fake_vision.instructions
            )
        )

    def test_rendered_appearance_is_not_a_rejection_reason_but_bad_inputs_are(self):
        prompt = " ".join(detection_service._PROMPT.split())
        self.assertIn("3D architectural renderings", prompt)
        self.assertIn("CGI exterior visualizations", prompt)
        self.assertIn("computer-generated images", prompt)
        self.assertIn("Do not mark an image unusable merely because", prompt)
        self.assertIn("too blurry", prompt)
        self.assertIn("extremely dark", prompt)
        self.assertIn("mostly hidden or cropped", prompt)
        self.assertIn("interior", prompt)
        self.assertIn("floor plan or unrelated drawing", prompt)

        class FakeVision:
            def __init__(self, reason):
                self.reason = reason

            def analyze_image(self, image, instructions, schema, prompt_version):
                return VisionResult(
                    data=SimpleNamespace(
                        usable=False,
                        quality_reason=self.reason,
                        components=[],
                    ),
                    attempts=1,
                    duration_ms=1,
                    model_name="mock-vision",
                    raw_text_excerpt="{}",
                )

        for kind, reason in (
            ("blurry", "Too blurry to identify exterior surfaces."),
            ("interior", "This is an interior image, not a house exterior."),
            ("floor plan", "A floor plan does not show exterior components."),
        ):
            with self.subTest(kind=kind):
                project_response = self.client.post(
                    "/api/projects", json={"name": f"Reject {kind}"}
                )
                project = project_response.json()
                upload = self.client.post(
                    f"/api/projects/{project['id']}/photos",
                    files={
                        "file": (
                            f"{kind}.jpg",
                            self.image_bytes(),
                            "image/jpeg",
                        )
                    },
                )
                self.assertEqual(upload.status_code, 201, upload.text)
                photo = upload.json()
                with patch(
                    "app.services.detection_service.get_vision_client",
                    return_value=FakeVision(reason),
                ):
                    response = self.client.post(
                        f"/api/projects/{project['id']}/photos/{photo['id']}/detect"
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertFalse(response.json()["usable"])
                self.assertEqual(response.json()["components"], [])
                self.assertFalse(response.json()["photo"]["quality_usable"])

    def test_successful_zero_component_detection_has_warning_and_completes_photo(self):
        self.settings = Settings(
            _env_file=None,
            DATABASE_PATH=self.db_path,
            STORAGE_ROOT=self.storage_path,
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            AI_MOCK_SCENARIO="no_components",
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=100_000,
        )
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        with patch("app.services.ai.mock.time.sleep"):
            response = self.detect()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["usable"])
        self.assertEqual(data["components"], [])
        self.assertEqual(
            data["warnings"],
            ["No components were found. You can add regions manually."],
        )
        self.assertTrue(data["photo"]["quality_usable"])
        self.assertIsNotNone(data["photo"]["detected_at"])

    def test_unusable_detection_keeps_components_and_marks_run_succeeded(self):
        conn = self.connect()
        try:
            component = component_repo.create(
                conn,
                self.project["id"],
                self.photo["id"],
                "wall",
                "User wall",
                0.1,
                0.1,
                0.5,
                0.5,
                origin="user",
                is_locked=1,
            )
            conn.commit()
        finally:
            conn.close()

        self.settings = Settings(
            _env_file=None,
            DATABASE_PATH=self.db_path,
            STORAGE_ROOT=self.storage_path,
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            AI_MOCK_SCENARIO="unusable",
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=100_000,
        )
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        with patch("app.services.ai.mock.time.sleep"):
            response = self.detect()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertFalse(result["usable"])
        self.assertEqual([item["id"] for item in result["components"]], [component["id"]])
        self.assertFalse(result["photo"]["quality_usable"])
        conn = self.connect()
        try:
            self.assertEqual(
                stage_run_repo.get_by_id(conn, result["stage_run_id"])["status"],
                "succeeded",
            )
        finally:
            conn.close()

    def test_redetection_preserves_locked_component_but_persists_detection_record(self):
        with patch("app.services.ai.mock.time.sleep"):
            first = self.detect()
        self.assertEqual(first.status_code, 200, first.text)
        conn = self.connect()
        try:
            wall = conn.execute(
                "SELECT id FROM components WHERE photo_id = ? AND type = 'wall'",
                (self.photo["id"],),
            ).fetchone()
            component_repo.update(
                conn,
                wall["id"],
                self.project["id"],
                label="My corrected wall",
            )
            conn.commit()
        finally:
            conn.close()

        with patch("app.services.ai.mock.time.sleep"):
            second = self.detect()
        self.assertEqual(second.status_code, 200, second.text)
        result = second.json()
        self.assertEqual(result["kept_locked_count"], 1)
        locked = next(item for item in result["components"] if item["id"] == wall["id"])
        self.assertEqual(locked["label"], "My corrected wall")
        self.assertTrue(locked["is_locked"])
        self.assertEqual(len(result["components"]), 11)

        conn = self.connect()
        try:
            detected = conn.execute(
                "SELECT COUNT(*) FROM detected_components WHERE photo_id = ?",
                (self.photo["id"],),
            ).fetchone()[0]
            self.assertEqual(detected, 22)
        finally:
            conn.close()

    def test_preprocessing_failure_marks_created_run_failed(self):
        with patch(
            "app.services.detection_service.prepare_working_image",
            side_effect=RuntimeError("test preprocessing failure"),
        ):
            response = self.detect()
        self.assertEqual(response.status_code, 500, response.text)
        conn = self.connect()
        try:
            run = conn.execute(
                "SELECT status, error_code FROM stage_runs WHERE project_id = ?",
                (self.project["id"],),
            ).fetchone()
            self.assertEqual((run["status"], run["error_code"]), ("failed", "INTERNAL_ERROR"))
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM components WHERE photo_id = ?",
                    (self.photo["id"],),
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()

    def test_invalid_component_entries_are_dropped_without_retry(self):
        class FakeVision:
            def analyze_image(self, image, instructions, schema, prompt_version):
                return VisionResult(
                    data=SimpleNamespace(
                        usable=True,
                        quality_reason=None,
                        components=[
                            {"type": "wall", "label": "Wall", "box_2d": [0, 0, 500, 500]},
                            {"type": "wall", "box_2d": [1, 2]},
                            {"type": "alien-type", "label": "", "box_2d": [100, 100, 500, 500]},
                        ],
                    ),
                    attempts=1,
                    duration_ms=1,
                    model_name="mock-vision",
                    raw_text_excerpt="{}",
                )

        with patch(
            "app.services.detection_service.get_vision_client",
            return_value=FakeVision(),
        ):
            response = self.detect()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(len(result["components"]), 2)
        self.assertTrue(any("invalid region entries" in warning for warning in result["warnings"]))
        self.assertTrue(any("unrecognised types" in warning for warning in result["warnings"]))

    def test_concurrent_detection_guard_is_project_scoped(self):
        conn = self.connect()
        try:
            with transaction(conn, immediate=True):
                run = stage_run_repo.create(conn, self.project["id"], "detection")
        finally:
            conn.close()
        response = self.detect()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["details"]["reason"], "detection_in_progress")
        conn = self.connect()
        try:
            self.assertEqual(stage_run_repo.get_by_id(conn, run["id"])["status"], "running")
        finally:
            conn.close()

    def test_ai_failure_scenarios_mark_runs_failed_and_preserve_components(self):
        conn = self.connect()
        try:
            preserved = component_repo.create(
                conn,
                self.project["id"],
                self.photo["id"],
                "wall",
                "Protected wall",
                0.1,
                0.1,
                0.3,
                0.3,
                origin="user",
                is_locked=1,
            )
            conn.commit()
        finally:
            conn.close()

        for scenario, expected_code in (
            ("invalid_json", "AI_INVALID_RESPONSE"),
            ("blocked", "AI_CONTENT_BLOCKED"),
            ("timeout", "AI_TIMEOUT"),
            ("rate_limited", "AI_RATE_LIMITED"),
        ):
            with self.subTest(scenario=scenario):
                self.settings = Settings(
                    _env_file=None,
                    DATABASE_PATH=self.db_path,
                    STORAGE_ROOT=self.storage_path,
                    CATALOGUE_PATH="backend/app/data/catalogue.json",
                    FRONTEND_DIR="frontend",
                    AI_MOCK_MODE=True,
                    AI_MOCK_SCENARIO=scenario,
                    MIN_IMAGE_SHORT_SIDE_PX=32,
                    MAX_IMAGE_PIXELS=100_000,
                )
                self.app.dependency_overrides[get_settings] = lambda: self.settings
                with patch("app.services.ai.mock.time.sleep"):
                    response = self.detect()
                self.assertEqual(response.status_code, 502 if scenario == "invalid_json" else {
                    "AI_CONTENT_BLOCKED": 422,
                    "AI_TIMEOUT": 504,
                    "AI_RATE_LIMITED": 429,
                }[expected_code], response.text)
                self.assertEqual(response.json()["error"]["code"], expected_code)
                conn = self.connect()
                try:
                    runs = stage_run_repo.list_by_project(
                        conn, self.project["id"], stage="detection"
                    )
                    self.assertEqual(runs[0]["status"], "failed")
                    self.assertEqual(runs[0]["error_code"], expected_code)
                    self.assertEqual(
                        component_repo.get_by_id(conn, preserved["id"])["label"],
                        "Protected wall",
                    )
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
