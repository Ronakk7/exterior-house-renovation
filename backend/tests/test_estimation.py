"""Deterministic cost examples and estimation API tests."""

import io
import os
import re
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
from app.core.database import get_connection
from app.main import create_app
from app.services.cost_service import compute_estimate


class TestCostService(unittest.TestCase):
    def setUp(self):
        self.components = {
            "cmp_a": {"id": "cmp_a", "type": "wall", "label": "Wall", "created_at": "1"},
            "cmp_b": {"id": "cmp_b", "type": "railing", "label": "Railing", "created_at": "2"},
            "cmp_c": {"id": "cmp_c", "type": "pillar", "label": "Pillar", "created_at": "3"},
        }
        self.materials = {
            "paint": {
                "id": "paint", "name": "Paint", "category": "paint",
                "pricing_unit": "sqft", "purchase_unit": "litre",
                "coverage_per_purchase_unit": 90,
            },
            "glass": {
                "id": "glass", "name": "Glass", "category": "glass_railing",
                "pricing_unit": "rft", "purchase_unit": None,
                "coverage_per_purchase_unit": None,
            },
            "stone": {
                "id": "stone", "name": "Stone", "category": "stone_cladding",
                "pricing_unit": "sqft", "purchase_unit": None,
                "coverage_per_purchase_unit": None,
            },
        }
        self.selections = [
            {"component_id": "cmp_a", "material_id": "paint"},
            {"component_id": "cmp_b", "material_id": "glass"},
            {"component_id": "cmp_c", "material_id": "stone"},
        ]
        self.measurements = {
            "cmp_a": {
                "input_mode": "dimensions", "area_sqft": 300,
                "deduction_sqft": 40, "uncertainty_pct": 15, "source": "user",
            },
            "cmp_b": {
                "input_mode": "length", "length_ft": 24,
                "uncertainty_pct": 15, "source": "user",
            },
            "cmp_c": {
                "input_mode": "area", "area_sqft": 120,
                "deduction_sqft": 0, "uncertainty_pct": 25, "source": "ai_estimate",
            },
        }
        self.rates = {
            "paint": {
                "material_rate": 14, "labour_rate": 10, "wastage_pct": 5,
                "is_overridden": False,
            },
            "glass": {
                "material_rate": 2600, "labour_rate": 400, "wastage_pct": 3,
                "is_overridden": False,
            },
            "stone": {
                "material_rate": 140, "labour_rate": 70, "wastage_pct": 12,
                "is_overridden": False,
            },
        }

    def calculate(self, selections=None, categories=None):
        return compute_estimate(
            "var_test", "INR", self.selections if selections is None else selections,
            self.components, self.measurements, self.materials, self.rates,
            categories or ["paint", "stone_cladding", "glass_railing"],
        )

    def test_examples_a_b_c_and_combined_totals(self):
        result = self.calculate()
        a, b, c = result["line_items"]
        self.assertEqual(
            (a["measure_value"], a["quantity_with_wastage"], a["material_cost"],
             a["labour_cost"], a["line_total"], a["purchase_quantity"],
             a["low_total"], a["high_total"]),
            (260, 273, 3822, 2600, 6422, 4, 5458.7, 7385.3),
        )
        self.assertEqual(
            (b["quantity_with_wastage"], b["material_cost"], b["labour_cost"],
             b["line_total"], b["purchase_quantity"], b["low_total"], b["high_total"]),
            (24.72, 64272, 9600, 73872, None, 62791.2, 84952.8),
        )
        self.assertEqual(
            (c["quantity_with_wastage"], c["material_cost"], c["labour_cost"],
             c["line_total"], c["low_total"], c["high_total"]),
            (134.4, 18816, 8400, 27216, 20412, 34020),
        )
        self.assertEqual(result["grand_total"], 107510)
        self.assertEqual(result["grand_total_low"], 88661.9)
        self.assertEqual(result["grand_total_high"], 126358.1)
        self.assertEqual(
            [row["category"] for row in result["category_totals"]],
            ["paint", "stone_cladding", "glass_railing"],
        )

    def test_example_d_rate_overrides(self):
        self.rates["paint"].update(labour_rate=12, is_overridden=True)
        result = self.calculate([self.selections[0]])
        self.assertEqual(result["line_items"][0]["labour_cost"], 3120)
        self.assertEqual(result["line_items"][0]["line_total"], 6942)
        self.rates["paint"].update(wastage_pct=0)
        result = self.calculate([self.selections[0]])
        self.assertEqual(result["line_items"][0]["quantity_with_wastage"], 260)
        self.assertEqual(result["line_items"][0]["material_cost"], 3640)
        self.assertEqual(result["line_items"][0]["purchase_quantity"], 3)

    def test_example_e_round_half_up(self):
        components = {"cmp_a": self.components["cmp_a"]}
        material = {"paint": self.materials["paint"]}
        rates = {"paint": {"material_rate": 0.345, "labour_rate": 0, "wastage_pct": 0, "is_overridden": True}}
        result = compute_estimate(
            "var_test", "INR",
            [{"component_id": "cmp_a", "material_id": "paint"}],
            components,
            {"cmp_a": {"input_mode": "area", "area_sqft": 1, "deduction_sqft": 0,
                       "uncertainty_pct": 0, "source": "user"}},
            material, rates, ["paint"],
        )
        self.assertEqual(result["line_items"][0]["material_cost"], 0.35)

    def test_example_f_missing_measurement_and_disclaimer(self):
        del self.measurements["cmp_a"]
        result = self.calculate([self.selections[0]])
        self.assertEqual(result["line_items"], [])
        self.assertEqual(result["grand_total"], 0)
        self.assertEqual(result["missing_measurements"][0]["component_id"], "cmp_a")
        self.assertIn(
            "Some selected regions have no usable measurement and are not included in the totals.",
            result["disclaimers"],
        )

    def test_zero_net_area_and_default_rate_disclaimer_condition(self):
        self.measurements["cmp_a"]["deduction_sqft"] = 300
        result = self.calculate([self.selections[0]])
        self.assertEqual(result["line_items"][0]["measure_value"], 0)
        self.assertEqual(result["line_items"][0]["line_total"], 0)
        self.assertTrue(any("Default rates" in text for text in result["disclaimers"]))
        self.rates["paint"]["is_overridden"] = True
        result = self.calculate([self.selections[0]])
        self.assertFalse(any("Default rates" in text for text in result["disclaimers"]))


class TestEstimationAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.settings = self.make_settings("ok")
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        project = self.client.post("/api/projects", json={"name": "Estimate test"})
        self.assertEqual(project.status_code, 201, project.text)
        self.project = project.json()
        image = io.BytesIO()
        Image.new("RGB", (640, 480), (110, 125, 135)).save(image, format="JPEG")
        upload = self.client.post(
            f"/api/projects/{self.project['id']}/photos",
            files={"file": ("house.jpg", image.getvalue(), "image/jpeg")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        self.photo = upload.json()
        self.wall = self.create_component("wall", "Front wall")
        self.railing = self.create_component("railing", "Front railing")
        self.variant_id = self.project["active_variant_id"]
        for component, material in (
            (self.wall, "paint_emulsion_matte"),
            (self.railing, "glass_railing_clear"),
        ):
            selected = self.client.put(
                f"/api/projects/{self.project['id']}/variants/{self.variant_id}/selections/{component['id']}",
                json={"material_id": material, "params": {}},
            )
            self.assertEqual(selected.status_code, 200, selected.text)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_settings(self, scenario):
        return Settings(
            _env_file=None,
            DATABASE_PATH=str(Path(self.temp_dir) / "app.db"),
            STORAGE_ROOT=str(Path(self.temp_dir) / "storage"),
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            AI_MOCK_SCENARIO=scenario,
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=1_000_000,
        )

    def create_component(self, component_type, label):
        response = self.client.post(
            f"/api/projects/{self.project['id']}/components",
            json={
                "photo_id": self.photo["id"],
                "type": component_type,
                "label": label,
                "box": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.4},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_measurement_modes_validation_and_user_source(self):
        dimensions = self.client.put(
            f"/api/projects/{self.project['id']}/components/{self.wall['id']}/measurement",
            json={"input_mode": "dimensions", "width_ft": 30, "height_ft": 10,
                  "deduction_sqft": 40, "uncertainty_pct": 15},
        )
        self.assertEqual(dimensions.status_code, 200, dimensions.text)
        self.assertEqual(dimensions.json()["area_sqft"], 300)
        self.assertEqual(dimensions.json()["net_area_sqft"], 260)
        self.assertEqual(dimensions.json()["source"], "user")
        repeated = self.client.put(
            f"/api/projects/{self.project['id']}/components/{self.wall['id']}/measurement",
            json={"input_mode": "area", "area_sqft": 100},
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertIsNone(repeated.json()["width_ft"])
        self.assertEqual(repeated.json()["area_sqft"], 100)
        wrong_mode = self.client.put(
            f"/api/projects/{self.project['id']}/components/{self.railing['id']}/measurement",
            json={"input_mode": "dimensions", "width_ft": 3, "height_ft": 4},
        )
        self.assertEqual(wrong_mode.status_code, 422)
        bad_deduction = self.client.put(
            f"/api/projects/{self.project['id']}/components/{self.wall['id']}/measurement",
            json={"input_mode": "area", "area_sqft": 10, "deduction_sqft": 11},
        )
        self.assertEqual(bad_deduction.status_code, 422)

    def test_rates_partial_update_reset_and_estimate_recomputes(self):
        rates_url = f"/api/projects/{self.project['id']}/rates"
        defaults = self.client.get(rates_url).json()["items"]
        paint = next(item for item in defaults if item["material_id"] == "paint_emulsion_matte")
        self.assertFalse(paint["is_overridden"])
        updated = self.client.put(
            f"{rates_url}/paint_emulsion_matte",
            json={"labour_rate": 12},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json()["is_overridden"])
        self.assertEqual(updated.json()["material_rate"], paint["material_rate"])
        self.client.put(
            f"/api/projects/{self.project['id']}/components/{self.wall['id']}/measurement",
            json={"input_mode": "area", "area_sqft": 1},
        )
        estimate = self.client.get(
            f"/api/projects/{self.project['id']}/variants/{self.variant_id}/estimate"
        )
        self.assertEqual(estimate.status_code, 200, estimate.text)
        self.assertEqual(estimate.json()["line_items"][0]["labour_cost"], 12)
        reset = self.client.put(
            f"{rates_url}/paint_emulsion_matte",
            json={"material_rate": None, "labour_rate": None, "wastage_pct": None},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertFalse(reset.json()["is_overridden"])

    def test_mock_ai_estimate_uses_refs_and_preserves_user_measurement(self):
        self.client.put(
            f"/api/projects/{self.project['id']}/components/{self.wall['id']}/measurement",
            json={"input_mode": "area", "area_sqft": 120},
        )
        with patch("app.services.ai.mock.time.sleep"):
            result = self.client.post(
                f"/api/projects/{self.project['id']}/measurements/ai-estimate",
                json={"component_ids": [self.wall["id"], self.railing["id"]]},
            )
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["component_id"], self.railing["id"])
        self.assertEqual(data["items"][0]["source"], "ai_estimate")
        self.assertIn(
            {"component_id": self.wall["id"], "reason": "has_measurement"},
            data["skipped"],
        )
        measurements = self.client.get(
            f"/api/projects/{self.project['id']}/measurements"
        ).json()["items"]
        preserved = next(item for item in measurements if item["component_id"] == self.wall["id"])
        self.assertEqual(preserved["source"], "user")
        self.assertEqual(preserved["area_sqft"], 120)

    def test_ai_invalid_item_is_skipped_and_prompt_hides_real_ids(self):
        def fake_analyze(image, instructions, schema, prompt_version, timeout_s=None):
            self.assertNotIn(self.wall["id"], instructions)
            self.assertEqual(prompt_version, "est-v2")
            self.assertIn("3D architectural rendering", instructions)
            self.assertIn("not verified physical measurements", instructions)
            component_ref = re.search(
                r"ESTIMATE ONLY: (c\d+) \(wall\)", instructions
            ).group(1)
            return SimpleNamespace(
                data=SimpleNamespace(
                    estimates=[{
                        "component_ref": component_ref,
                        "input_mode": "length",
                        "length_ft": 10,
                    }]
                ),
                attempts=1,
                model_name="mock",
            )

        with patch("app.services.measurement_service.get_vision_client") as factory, \
             patch("app.services.ai.image_prep.prepare_working_image") as prep:
            factory.return_value.analyze_image.side_effect = fake_analyze
            prep.return_value = SimpleNamespace(bytes=b"x", mime_type="image/jpeg")
            response = self.client.post(
                f"/api/projects/{self.project['id']}/measurements/ai-estimate",
                json={"component_ids": [self.wall["id"]]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(
            response.json()["skipped"],
            [{"component_id": self.wall["id"], "reason": "invalid_estimate"}],
        )

    def test_ai_failure_marks_stage_failed_without_measurements(self):
        self.settings = self.make_settings("timeout")
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        with patch("app.services.ai.mock.time.sleep"):
            response = self.client.post(
                f"/api/projects/{self.project['id']}/measurements/ai-estimate",
                json={"component_ids": [self.wall["id"]]},
            )
        self.assertEqual(response.status_code, 504, response.text)
        self.assertEqual(response.json()["error"]["code"], "AI_TIMEOUT")
        conn = get_connection(self.settings.DATABASE_PATH)
        try:
            run = conn.execute(
                "SELECT status, error_code FROM stage_runs WHERE stage = 'ai_estimate'"
            ).fetchone()
            self.assertEqual(tuple(run), ("failed", "AI_TIMEOUT"))
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM component_measurements WHERE component_id = ?",
                    (self.wall["id"],),
                ).fetchone()
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
