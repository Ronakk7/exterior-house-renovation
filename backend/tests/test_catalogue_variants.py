"""Catalogue, variant, and material selection API tests."""

import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.database import get_connection
from app.main import create_app
from app.services.catalogue_service import load_catalogue, validate_catalogue


class TestCatalogueAndSelection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.settings = Settings(
            DATABASE_PATH=os.path.join(self.temp_dir, "app.db"),
            STORAGE_ROOT=os.path.join(self.temp_dir, "storage"),
            CATALOGUE_PATH="backend/app/data/catalogue.json",
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
            MIN_IMAGE_SHORT_SIDE_PX=32,
            MAX_IMAGE_PIXELS=100_000,
        )
        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        project = self.client.post("/api/projects", json={"name": "Catalogue test"})
        self.assertEqual(project.status_code, 201, project.text)
        self.project = project.json()
        upload = self.client.post(
            f"/api/projects/{self.project['id']}/photos",
            files={"file": ("house.jpg", self.image_bytes(), "image/jpeg")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        self.photo = upload.json()
        component = self.client.post(
            f"/api/projects/{self.project['id']}/components",
            json={
                "photo_id": self.photo["id"],
                "type": "wall",
                "label": "Front wall",
                "box": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
            },
        )
        self.assertEqual(component.status_code, 201, component.text)
        self.component = component.json()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def image_bytes():
        output = io.BytesIO()
        Image.new("RGB", (160, 120), (120, 80, 40)).save(output, format="JPEG")
        return output.getvalue()

    def variants_url(self):
        return f"/api/projects/{self.project['id']}/variants"

    def set_selection(self, variant_id, material_id="paint_emulsion_matte", params=None):
        return self.client.put(
            f"{self.variants_url()}/{variant_id}/selections/{self.component['id']}",
            json={"material_id": material_id, "params": params or {}},
        )

    def test_starter_catalogue_and_compatibility_endpoints(self):
        catalogue = self.client.get("/api/catalogue")
        self.assertEqual(catalogue.status_code, 200, catalogue.text)
        self.assertEqual(catalogue.headers["Cache-Control"], "public, max-age=300")
        data = catalogue.json()
        self.assertEqual(len(data["materials"]), 18)
        self.assertEqual(len(data["categories"]), 8)
        self.assertEqual(
            set(data["type_map"]),
            {"wall", "pillar", "balcony", "parapet", "gate", "roof_edge", "railing"},
        )
        railing = self.client.get("/api/catalogue/materials?component_type=railing")
        self.assertEqual(railing.status_code, 200)
        self.assertTrue(all("railing" in item["compatible_types"] for item in railing.json()["items"]))
        self.assertEqual(
            self.client.get("/api/catalogue/materials?component_type=window").json()["items"],
            [],
        )
        unknown = self.client.get("/api/catalogue/materials?component_type=foo")
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(unknown.json()["error"]["code"], "VALIDATION_ERROR")

    def test_catalogue_loader_rejects_duplicate_ids_mixed_units_and_invalid_coverage(self):
        path = Path(__file__).resolve().parents[1] / "app" / "data" / "catalogue.json"
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        duplicate = copy.deepcopy(catalogue)
        duplicate["materials"][1]["id"] = duplicate["materials"][0]["id"]
        with self.assertRaisesRegex(RuntimeError, "duplicate material ID"):
            validate_catalogue(duplicate)

        mixed = copy.deepcopy(catalogue)
        mixed["materials"][0]["pricing_unit"] = "rft"
        with self.assertRaisesRegex(RuntimeError, "pricing_unit conflicts"):
            validate_catalogue(mixed)

        invalid_coverage = copy.deepcopy(catalogue)
        invalid_coverage["materials"][0]["purchase_unit"] = None
        with self.assertRaisesRegex(RuntimeError, "must both be set or null"):
            validate_catalogue(invalid_coverage)

        invalid_swatch = copy.deepcopy(catalogue)
        invalid_swatch["materials"][0]["swatch_hex"] = "beige"
        with self.assertRaisesRegex(RuntimeError, "swatch_hex"):
            validate_catalogue(invalid_swatch)

        loaded = load_catalogue(str(path))
        self.assertEqual(loaded["type_map"]["wall"][0], "paint_emulsion_matte")

    def test_selection_validation_upsert_and_canonical_parameters(self):
        variant_id = self.project["active_variant_id"]
        selected = self.set_selection(
            variant_id,
            params={"note": "  warm tone  ", "color_hex": "#c8b8a0"},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.json()["params"], {"color_hex": "#C8B8A0", "note": "warm tone"})

        replaced = self.set_selection(variant_id, "stone_cladding_slate")
        self.assertEqual(replaced.status_code, 200, replaced.text)
        variants = self.client.get(self.variants_url()).json()["items"]
        self.assertEqual(len(variants[0]["selections"]), 1)
        self.assertEqual(variants[0]["selections"][0]["material_id"], "stone_cladding_slate")

        incompatible = self.set_selection(variant_id, "glass_clear_toughened")
        self.assertEqual(incompatible.status_code, 422)
        self.assertEqual(incompatible.json()["error"]["code"], "MATERIAL_INCOMPATIBLE")
        invalid_color = self.set_selection(
            variant_id, "stone_cladding_slate", {"color_hex": "#FFFFFF"}
        )
        self.assertEqual(invalid_color.status_code, 422)
        self.assertEqual(invalid_color.json()["error"]["code"], "VALIDATION_ERROR")
        invalid_key = self.set_selection(
            variant_id, params={"unknown": "value"}
        )
        self.assertEqual(invalid_key.status_code, 422)

    def test_variants_case_insensitive_names_copy_switch_and_delete(self):
        created = self.client.post(self.variants_url(), json={"name": "Summer"})
        self.assertEqual(created.status_code, 201, created.text)
        duplicate = self.client.post(self.variants_url(), json={"name": "summer"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["details"]["reason"], "duplicate_name")

        initial_id = self.project["active_variant_id"]
        self.assertEqual(self.set_selection(initial_id).status_code, 200)
        copied = self.client.post(
            self.variants_url(),
            json={"name": "Summer copy", "copy_from_variant_id": initial_id},
        )
        self.assertEqual(copied.status_code, 201, copied.text)
        self.assertEqual(len(copied.json()["selections"]), 1)

        switched = self.client.patch(
            f"/api/projects/{self.project['id']}",
            json={"active_variant_id": created.json()["id"]},
        )
        self.assertEqual(switched.status_code, 200, switched.text)
        variant_list = self.client.get(self.variants_url()).json()["items"]
        self.assertTrue(next(item for item in variant_list if item["id"] == created.json()["id"])["is_active"])

        renamed = self.client.patch(
            f"{self.variants_url()}/{created.json()['id']}",
            json={"name": "Summer 2026"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "Summer 2026")

        deleted_active = self.client.delete(f"{self.variants_url()}/{created.json()['id']}")
        self.assertEqual(deleted_active.status_code, 204)
        project = self.client.get(f"/api/projects/{self.project['id']}").json()
        self.assertNotEqual(project["active_variant_id"], created.json()["id"])
        variants = self.client.get(self.variants_url()).json()["items"]
        self.assertEqual(len(variants), 2)

        while len(variants) < 10:
            response = self.client.post(
                self.variants_url(), json={"name": f"Design extra {len(variants)}"}
            )
            self.assertEqual(response.status_code, 201, response.text)
            variants = self.client.get(self.variants_url()).json()["items"]
        limited = self.client.post(self.variants_url(), json={"name": "Eleventh"})
        self.assertEqual(limited.status_code, 409)
        self.assertEqual(limited.json()["error"]["details"]["reason"], "variant_limit")

    def test_deleting_last_variant_and_selection_delete(self):
        variant_id = self.project["active_variant_id"]
        selected = self.set_selection(variant_id)
        self.assertEqual(selected.status_code, 200)
        removed = self.client.delete(
            f"{self.variants_url()}/{variant_id}/selections/{self.component['id']}"
        )
        self.assertEqual(removed.status_code, 204)
        absent = self.client.delete(
            f"{self.variants_url()}/{variant_id}/selections/{self.component['id']}"
        )
        self.assertEqual(absent.status_code, 404)
        last_variant = self.client.delete(f"{self.variants_url()}/{variant_id}")
        self.assertEqual(last_variant.status_code, 409)
        self.assertEqual(last_variant.json()["error"]["details"]["reason"], "last_variant")


if __name__ == "__main__":
    unittest.main()
