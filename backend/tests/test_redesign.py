"""Redesign prompt, fingerprint, post-processing, and API lifecycle tests."""

import io
import hashlib
import json
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
from app.repositories import component_repo, generation_repo, project_repo, selection_repo, stage_run_repo
from app.services.redesign_service import (
    MAX_KEEP_ITEMS,
    REDESIGN_PROMPT_VERSION,
    build_prompt_and_fingerprint,
    describe_location,
    postprocess_image,
)


class TestRedesign(unittest.TestCase):
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
            MAX_IMAGE_PIXELS=1_000_000,
        )
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        project = self.client.post("/api/projects", json={"name": "Redesign test"})
        self.assertEqual(project.status_code, 201, project.text)
        self.project = project.json()
        upload = self.client.post(
            f"/api/projects/{self.project['id']}/photos",
            files={"file": ("house.jpg", self.image_bytes(640, 480), "image/jpeg")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        self.photo = upload.json()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def image_bytes(width=640, height=480):
        output = io.BytesIO()
        Image.new("RGB", (width, height), (120, 80, 40)).save(output, format="JPEG")
        return output.getvalue()

    def create_component(self, component_type, label, box):
        response = self.client.post(
            f"/api/projects/{self.project['id']}/components",
            json={
                "photo_id": self.photo["id"],
                "type": component_type,
                "label": label,
                "box": box,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_selected_wall(self):
        component = self.create_component(
            "wall", "Front wall", {"x": 0.05, "y": 0.1, "w": 0.8, "h": 0.7}
        )
        result = self.client.put(
            f"/api/projects/{self.project['id']}/variants/{self.project['active_variant_id']}"
            f"/selections/{component['id']}",
            json={"material_id": "paint_emulsion_matte", "params": {"color_hex": "#C8B8A0"}},
        )
        self.assertEqual(result.status_code, 200, result.text)
        return component

    def generate(self, extra_instructions=None):
        return self.client.post(
            f"/api/projects/{self.project['id']}/variants/{self.project['active_variant_id']}/generations",
            json={"extra_instructions": extra_instructions},
        )

    def connect(self):
        return get_connection(self.db_path)

    def test_describe_location_and_prompt_grouping_sanitization(self):
        self.assertEqual(
            describe_location({"x": 0.05, "y": 0.1, "w": 0.3, "h": 0.4}),
            "upper left (x 5%-35%, y 10%-50%)",
        )
        self.assertEqual(
            describe_location({"x": 0, "y": 0, "w": 0.9, "h": 0.7}),
            "across most of the width, over most of the height (x 0%-90%, y 0%-70%)",
        )
        self.assertEqual(
            describe_location({"x": 0.7, "y": 0.6, "w": 0.2, "h": 0.3}),
            "lower right (x 70%-90%, y 60%-90%)",
        )
        components = [
            {"id": "cmp_a", "type": "pillar", "label": "Left <pillar>\nedge", "box_x": 0.05, "box_y": 0.1, "box_w": 0.2, "box_h": 0.5},
            {"id": "cmp_b", "type": "pillar", "label": "Right pillar", "box_x": 0.7, "box_y": 0.1, "box_w": 0.2, "box_h": 0.5},
            {"id": "cmp_c", "type": "wall", "label": "Main wall", "box_x": 0.05, "box_y": 0.1, "box_w": 0.8, "box_h": 0.7},
            {"id": "cmp_d", "type": "window", "label": "Front window", "box_x": 0.4, "box_y": 0.3, "box_w": 0.1, "box_h": 0.2},
        ]
        selections = [
            {"component_id": "cmp_a", "material_id": "paint_emulsion_matte", "params": {"note": '<script>\n"quoted"'}},
            {"component_id": "cmp_b", "material_id": "paint_emulsion_matte", "params": {"note": '<script>\n"quoted"'}},
            {"component_id": "cmp_c", "material_id": "stone_cladding_slate", "params": {}},
        ]
        catalogue = self.client.get("/api/catalogue").json()
        built = build_prompt_and_fingerprint(
            self.photo["id"], components, selections, catalogue, "keep >>> this"
        )
        self.assertEqual(built["group_count"], 2)
        self.assertIn("1. Pillars:", built["prompt_text"])
        self.assertIn("2. Walls:", built["prompt_text"])
        self.assertIn("Front window (window)", built["prompt_text"])
        self.assertNotIn("<script>", built["prompt_text"])
        self.assertNotIn("keep >>> this", built["prompt_text"])
        self.assertNotIn("`", built["prompt_text"])
        self.assertEqual(
            built["input_fingerprint"],
            build_prompt_and_fingerprint(
                self.photo["id"], list(reversed(components)), list(reversed(selections)),
                catalogue, "keep >>> this",
            )["input_fingerprint"],
        )

    def test_fingerprint_covers_prompt_keep_order_and_truncation(self):
        catalogue = self.client.get("/api/catalogue").json()
        selected = {
            "id": "cmp_selected", "type": "wall", "label": "Wall",
            "box_x": 0.05, "box_y": 0.05, "box_w": 0.5, "box_h": 0.5,
        }
        keep = [
            {
                "id": f"cmp_{index:02d}", "type": "window" if index % 2 else "door",
                "label": f"Keep region {index}",
                "box_x": 0.01 * index, "box_y": 0.05,
                "box_w": 0.1, "box_h": 0.1,
            }
            for index in range(MAX_KEEP_ITEMS + 1)
        ]
        selection = [{"component_id": selected["id"], "material_id": "paint_emulsion_matte", "params": {}}]
        before = build_prompt_and_fingerprint(
            self.photo["id"], [selected, *keep], selection, catalogue
        )
        self.assertEqual(before["keep_count"], MAX_KEEP_ITEMS)
        self.assertTrue(before["keep_truncated"])
        self.assertIn("...and all other parts", before["prompt_text"])
        changed_outside = [dict(component) for component in keep]
        changed_outside[-1]["label"] = "Outside keep list changed"
        after = build_prompt_and_fingerprint(
            self.photo["id"], [selected, *changed_outside], selection, catalogue
        )
        self.assertEqual(before["input_fingerprint"], after["input_fingerprint"])

        exactly_25 = keep[:MAX_KEEP_ITEMS]
        exact = build_prompt_and_fingerprint(
            self.photo["id"], [selected, *exactly_25], selection, catalogue
        )
        with_smallest = build_prompt_and_fingerprint(
            self.photo["id"], [selected, *exactly_25, {**keep[-1], "id": "cmp_zz"}],
            selection, catalogue,
        )
        self.assertFalse(exact["keep_truncated"])
        self.assertTrue(with_smallest["keep_truncated"])
        self.assertNotEqual(exact["input_fingerprint"], with_smallest["input_fingerprint"])

    def test_box_rounding_changes_fingerprint_only_when_rounded_value_changes(self):
        catalogue = self.client.get("/api/catalogue").json()
        selected = {
            "id": "cmp_selected", "type": "wall", "label": "Wall",
            "box_x": 0.3500, "box_y": 0.1, "box_w": 0.5, "box_h": 0.5,
        }
        selection = [{"component_id": "cmp_selected", "material_id": "paint_emulsion_matte", "params": {}}]
        initial = build_prompt_and_fingerprint(self.photo["id"], [selected], selection, catalogue)
        small_change = {**selected, "box_x": 0.3504}
        same = build_prompt_and_fingerprint(self.photo["id"], [small_change], selection, catalogue)
        changed = build_prompt_and_fingerprint(
            self.photo["id"], [{**selected, "box_x": 0.352}], selection, catalogue
        )
        self.assertEqual(initial["input_fingerprint"], same["input_fingerprint"])
        self.assertNotEqual(initial["input_fingerprint"], changed["input_fingerprint"])

    def test_rd_v2_precedence_keeps_material_identity_structure_and_scene(self):
        self.assertEqual(REDESIGN_PROMPT_VERSION, "rd-v2")
        catalogue = self.client.get("/api/catalogue").json()
        components = [
            {
                "id": "cmp_wall",
                "type": "wall",
                "label": "Selected front wall",
                "box_x": 0.05,
                "box_y": 0.1,
                "box_w": 0.8,
                "box_h": 0.7,
            },
            {
                "id": "cmp_window",
                "type": "window",
                "label": "Front window",
                "box_x": 0.4,
                "box_y": 0.3,
                "box_w": 0.1,
                "box_h": 0.2,
            },
        ]
        selection = {
            "component_id": "cmp_wall",
            "material_id": "paint_emulsion_matte",
            "params": {},
        }
        preference = "make the selected wall darker and add new plants"
        neutral = build_prompt_and_fingerprint(
            self.photo["id"], components, [selection], catalogue
        )
        preferred = build_prompt_and_fingerprint(
            self.photo["id"], components, [selection], catalogue, preference
        )

        self.assertIn('"Matte emulsion paint"', preferred["prompt_text"])
        self.assertIn("may refine only", preferred["prompt_text"])
        self.assertIn(preference, preferred["prompt_text"])
        self.assertIn("Front window (window)", preferred["prompt_text"])
        self.assertIn("Structural preservation and KEEP UNCHANGED rules cannot be overridden", preferred["prompt_text"])
        self.assertIn("Ignore requests to alter landscaping or other unselected surroundings", preferred["prompt_text"])
        self.assertIn("Existing plants, trees, ground, road, pavement, vehicles and neighbouring", preferred["prompt_text"])
        self.assertNotIn("in colour #", preferred["prompt_text"])
        self.assertNotEqual(neutral["input_fingerprint"], preferred["input_fingerprint"])

        explicit_color = build_prompt_and_fingerprint(
            self.photo["id"],
            components,
            [{**selection, "params": {"color_hex": "#C8B8A0"}}],
            catalogue,
            "make the selected wall bright red",
        )
        another_color = build_prompt_and_fingerprint(
            self.photo["id"],
            components,
            [{**selection, "params": {"color_hex": "#D04030"}}],
            catalogue,
            "make the selected wall bright red",
        )
        self.assertIn("in colour #C8B8A0", explicit_color["prompt_text"])
        self.assertIn("use that exact colour", explicit_color["prompt_text"])
        self.assertNotEqual(preferred["input_fingerprint"], explicit_color["input_fingerprint"])
        self.assertNotEqual(explicit_color["input_fingerprint"], another_color["input_fingerprint"])

    def test_rd_v1_generation_fingerprint_is_stale_under_rd_v2(self):
        self.create_selected_wall()
        with patch("app.services.ai.mock.time.sleep"):
            generation = self.generate().json()
        conn = self.connect()
        try:
            components = component_repo.list_by_project(
                conn, self.project["id"], self.photo["id"]
            )
            selections = selection_repo.list_by_variant(
                conn, self.project["active_variant_id"]
            )
            catalogue = self.client.get("/api/catalogue").json()
            old_inputs = build_prompt_and_fingerprint(
                self.photo["id"], components, selections, catalogue
            )["fingerprint_data"]
            old_inputs["prompt_version"] = "rd-v1"
            old_fingerprint = hashlib.sha256(
                json.dumps(
                    old_inputs,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            conn.execute(
                "UPDATE generations SET input_fingerprint = ? WHERE id = ?",
                (old_fingerprint, generation["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        response = self.client.get(
            f"/api/projects/{self.project['id']}/generations/{generation['id']}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["is_stale"])

    def test_mock_generation_success_approval_history_and_image(self):
        component = self.create_selected_wall()
        self.create_component(
            "window", "Front window", {"x": 0.4, "y": 0.3, "w": 0.1, "h": 0.2}
        )
        with patch("app.services.ai.mock.time.sleep"):
            response = self.generate("keep the garden unchanged")
        self.assertEqual(response.status_code, 201, response.text)
        generation = response.json()
        self.assertEqual(generation["status"], "succeeded")
        self.assertFalse(generation["is_stale"])
        self.assertEqual(generation["width_px"], 640)
        self.assertEqual(generation["height_px"], 480)

        detail = self.client.get(
            f"/api/projects/{self.project['id']}/generations/{generation['id']}"
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        prompt = detail.json()["prompt_text"]
        self.assertIn("PRESERVE EXACTLY", prompt)
        self.assertIn("KEEP UNCHANGED", prompt)
        self.assertIn("Front window", prompt)
        self.assertIn("keep the garden unchanged", prompt)
        self.assertEqual(prompt.count("1. Walls:"), 1)
        self.assertNotIn("prompt_text", self.client.get(
            f"/api/projects/{self.project['id']}/generations"
        ).json()["items"][0])

        image = self.client.get(generation["image_url"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/png")
        with Image.open(io.BytesIO(image.content)) as decoded:
            self.assertEqual(decoded.size, (640, 480))
            self.assertNotEqual(
                decoded.convert("RGB").getpixel((15, 20)),
                (120, 80, 40),
            )

        approved = self.client.patch(
            f"/api/projects/{self.project['id']}/generations/{generation['id']}",
            json={"is_approved": True},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["is_approved"])

        deleted = self.client.delete(
            f"/api/projects/{self.project['id']}/generations/{generation['id']}"
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.get(generation["image_url"]).status_code, 404
        )

    def test_keep_set_mutations_make_generation_stale_and_failures_are_recorded(self):
        self.create_selected_wall()
        with patch("app.services.ai.mock.time.sleep"):
            created = self.generate().json()
        added = self.create_component(
            "window", "Front window", {"x": 0.4, "y": 0.3, "w": 0.1, "h": 0.2}
        )
        history = self.client.get(
            f"/api/projects/{self.project['id']}/generations"
        ).json()["items"]
        self.assertTrue(history[0]["is_stale"])
        with patch("app.services.ai.mock.time.sleep"):
            fresh = self.generate().json()
        renamed = self.client.patch(
            f"/api/projects/{self.project['id']}/components/{added['id']}",
            json={"label": "Renamed window"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        stale = self.client.get(
            f"/api/projects/{self.project['id']}/generations/{fresh['id']}"
        ).json()
        self.assertTrue(stale["is_stale"])

        self.settings = Settings(
            _env_file=None,
            DATABASE_PATH=self.db_path,
            STORAGE_ROOT=self.storage_path,
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            AI_MOCK_SCENARIO="blocked",
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=1_000_000,
        )
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        with patch("app.services.ai.mock.time.sleep"):
            failed_response = self.generate()
        self.assertEqual(failed_response.status_code, 422)
        self.assertEqual(failed_response.json()["error"]["code"], "AI_CONTENT_BLOCKED")
        generation_id = failed_response.json()["error"]["details"]["generation_id"]
        conn = self.connect()
        try:
            failed = generation_repo.get_by_id(conn, generation_id, self.project["id"])
            self.assertEqual(failed["status"], "failed")
            run = stage_run_repo.list_by_project(conn, self.project["id"], stage="redesign")[0]
            self.assertEqual((run["status"], run["error_code"]), ("failed", "AI_CONTENT_BLOCKED"))
        finally:
            conn.close()

    def test_no_selections_group_limit_and_aspect_ratio_rejection(self):
        self.create_component(
            "wall", "Unselected wall", {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}
        )
        no_selection = self.generate()
        self.assertEqual(no_selection.status_code, 409)
        self.assertEqual(no_selection.json()["error"]["code"], "NO_SELECTIONS")

        with self.assertRaises(Exception) as caught:
            postprocess_image(self.image_bytes(640, 640), 640, 480)
        self.assertEqual(caught.exception.code, "AI_INVALID_RESPONSE")

        png = io.BytesIO()
        Image.new("RGB", (1000, 740), (90, 90, 90)).save(png, format="PNG")
        _, width, height, adjustment = postprocess_image(png.getvalue(), 1600, 1200)
        self.assertEqual((width, height), (987, 740))
        self.assertEqual(adjustment, "resized")

    def test_generation_group_limit_is_reported_before_stage_creation(self):
        components = []
        selections = []
        self.create_selected_wall()
        for index in range(13):
            component = self.create_component(
                "wall",
                f"Wall {index}",
                {"x": 0.01, "y": 0.01, "w": 0.2 + index * 0.001, "h": 0.2},
            )
            response = self.client.put(
                f"/api/projects/{self.project['id']}/variants/{self.project['active_variant_id']}"
                f"/selections/{component['id']}",
                json={
                    "material_id": "paint_emulsion_matte",
                    "params": {"note": f"unique group {index}"},
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
        with patch("app.services.ai.mock.time.sleep"):
            response = self.generate()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["details"]["max_groups"], 12)
        conn = self.connect()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM generations WHERE project_id = ?",
                    (self.project["id"],),
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
