"""Region editor CRUD, validation, compatibility and limit tests."""

import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.database import get_connection
from app.main import create_app
from app.repositories import component_repo, measurement_repo, project_repo, selection_repo


class TestComponentEditorAPI(unittest.TestCase):
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
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=100_000,
            MAX_COMPONENTS_PER_PHOTO=2,
        )
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        project = self.client.post("/api/projects", json={"name": "Editor test"})
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

    def connect(self):
        return get_connection(self.db_path)

    def create_component(self, component_type="wall", box=None, label=None):
        payload = {
            "photo_id": self.photo["id"],
            "type": component_type,
            "box": box or {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3},
        }
        if label is not None:
            payload["label"] = label
        return self.client.post(
            f"/api/projects/{self.project['id']}/components",
            json=payload,
        )

    def test_create_list_and_derive_supported_from_catalogue(self):
        response = self.create_component(label="  Front   wall  ")
        self.assertEqual(response.status_code, 201, response.text)
        component = response.json()
        self.assertEqual(component["label"], "Front wall")
        self.assertEqual(component["origin"], "user")
        self.assertTrue(component["is_locked"])
        self.assertTrue(component["supported"])

        unsupported = self.create_component("window")
        self.assertEqual(unsupported.status_code, 201, unsupported.text)
        self.assertFalse(unsupported.json()["supported"])

        listing = self.client.get(
            f"/api/projects/{self.project['id']}/components?photo_id={self.photo['id']}"
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        ordered = sorted(
            (component, unsupported.json()),
            key=lambda item: (item["created_at"], item["id"]),
        )
        self.assertEqual(
            [item["id"] for item in listing.json()["items"]],
            [item["id"] for item in ordered],
        )
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.project['id']}/components?photo_id=pho_0000000000000000"
            ).status_code,
            404,
        )

    def test_create_clamps_tolerance_and_enforces_minimum_box_size(self):
        response = self.create_component(box={"x": 0.8, "y": 0.2, "w": 0.2005, "h": 0.3})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["box"]["w"], 0.2)

        too_small = self.create_component(box={"x": 0.1, "y": 0.1, "w": 0.019, "h": 0.3})
        self.assertEqual(too_small.status_code, 422)
        self.assertEqual(too_small.json()["error"]["code"], "VALIDATION_ERROR")

        invalid_type = self.create_component("alien")
        self.assertEqual(invalid_type.status_code, 422)
        self.assertEqual(invalid_type.json()["error"]["code"], "VALIDATION_ERROR")

    def test_config_exposes_backend_component_limit_and_limit_is_atomic(self):
        config = self.client.get("/api/client-config").json()
        self.assertEqual(config["limits"]["max_components_per_photo"], 2)
        self.assertEqual(self.create_component().status_code, 201)
        self.assertEqual(self.create_component("window").status_code, 201)
        limited = self.create_component("door")
        self.assertEqual(limited.status_code, 409)
        self.assertEqual(limited.json()["error"]["details"]["reason"], "component_limit")

    def test_type_change_removes_incompatible_selection_and_ai_measurement(self):
        created = self.create_component()
        component = created.json()
        conn = self.connect()
        try:
            selection_repo.upsert(
                conn,
                self.project["active_variant_id"],
                component["id"],
                "paint_emulsion_matte",
            )
            measurement_repo.upsert(
                conn,
                component["id"],
                "dimensions",
                source="ai_estimate",
                width_ft=4,
                height_ft=5,
                uncertainty_pct=25,
            )
            conn.commit()
        finally:
            conn.close()

        response = self.client.patch(
            f"/api/projects/{self.project['id']}/components/{component['id']}",
            json={"type": "railing"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["component"]["type"], "railing")
        self.assertTrue(result["component"]["is_locked"])
        self.assertEqual(result["removed_selections"], 1)
        self.assertTrue(result["removed_ai_measurement"])
        self.assertEqual(len(result["warnings"]), 2)
        conn = self.connect()
        try:
            self.assertIsNone(selection_repo.get(conn, self.project["active_variant_id"], component["id"]))
            self.assertIsNone(measurement_repo.get_by_component(conn, component["id"]))
        finally:
            conn.close()

    def test_noop_patch_does_not_lock_and_user_measurement_survives_box_edit(self):
        conn = self.connect()
        try:
            component = component_repo.create(
                conn,
                self.project["id"],
                self.photo["id"],
                "wall",
                "AI wall",
                0.1,
                0.1,
                0.3,
                0.3,
                origin="ai",
                is_locked=0,
            )
            measurement_repo.upsert(
                conn,
                component["id"],
                "dimensions",
                source="user",
                width_ft=10,
                height_ft=8,
            )
            conn.commit()
        finally:
            conn.close()

        url = f"/api/projects/{self.project['id']}/components/{component['id']}"
        noop = self.client.patch(url, json={"label": "AI wall"})
        self.assertEqual(noop.status_code, 200, noop.text)
        self.assertFalse(noop.json()["component"]["is_locked"])
        self.assertEqual(noop.json()["warnings"], [])

        updated = self.client.patch(
            url,
            json={"box": {"x": 0.2, "y": 0.2, "w": 0.3, "h": 0.3}},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json()["component"]["is_locked"])
        self.assertIn("Your measurement", updated.json()["warnings"][0])
        conn = self.connect()
        try:
            self.assertEqual(measurement_repo.get_by_component(conn, component["id"])["source"], "user")
        finally:
            conn.close()

    def test_invalid_empty_patch_and_delete_cascades(self):
        component = self.create_component().json()
        url = f"/api/projects/{self.project['id']}/components/{component['id']}"
        empty = self.client.patch(url, json={})
        self.assertEqual(empty.status_code, 422)
        null_value = self.client.patch(url, json={"label": None})
        self.assertEqual(null_value.status_code, 422)

        conn = self.connect()
        try:
            selection_repo.upsert(
                conn,
                self.project["active_variant_id"],
                component["id"],
                "paint_emulsion_matte",
            )
            measurement_repo.upsert(
                conn,
                component["id"],
                "dimensions",
                source="user",
                width_ft=10,
                height_ft=8,
            )
            conn.commit()
        finally:
            conn.close()

        deleted = self.client.delete(url)
        self.assertEqual(deleted.status_code, 204)
        conn = self.connect()
        try:
            self.assertIsNone(component_repo.get_by_id(conn, component["id"]))
            self.assertIsNone(selection_repo.get(conn, self.project["active_variant_id"], component["id"]))
            self.assertIsNone(measurement_repo.get_by_component(conn, component["id"]))
        finally:
            conn.close()

    def test_upload_detection_and_user_edit_survive_redetection(self):
        with patch("app.services.ai.mock.time.sleep"):
            detected = self.client.post(
                f"/api/projects/{self.project['id']}/photos/{self.photo['id']}/detect"
            )
        self.assertEqual(detected.status_code, 200, detected.text)
        detected_components = detected.json()["components"]
        self.assertGreater(len(detected_components), 0)
        selected = detected_components[0]
        edited = self.client.patch(
            f"/api/projects/{self.project['id']}/components/{selected['id']}",
            json={"label": "Owner corrected region"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertTrue(edited.json()["component"]["is_locked"])

        with patch("app.services.ai.mock.time.sleep"):
            repeated = self.client.post(
                f"/api/projects/{self.project['id']}/photos/{self.photo['id']}/detect"
            )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        preserved = next(
            item
            for item in repeated.json()["components"]
            if item["id"] == selected["id"]
        )
        self.assertEqual(preserved["label"], "Owner corrected region")
        self.assertTrue(preserved["is_locked"])


if __name__ == "__main__":
    unittest.main()
