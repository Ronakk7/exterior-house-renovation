"""API integration tests exercising FastAPI lifespan, contracts, error formats, and security headers."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

from app.core.config import Settings
from app.api.deps import get_settings
from app.main import create_app


class TestAPIEndpoints(unittest.TestCase):
    """Test API contracts, endpoints, security headers, and error responses with full lifespan."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_app.db")
        self.storage_path = os.path.join(self.temp_dir, "storage")
        self.catalogue_path = "backend/app/data/catalogue.json"

        self.settings = Settings(
            APP_ENV="development",
            DATABASE_PATH=self.db_path,
            STORAGE_ROOT=self.storage_path,
            CATALOGUE_PATH=self.catalogue_path,
            FRONTEND_DIR="frontend",
            AI_MOCK_MODE=True,
        )

        self.app = create_app(self.settings)
        self.app.dependency_overrides[get_settings] = lambda: self.settings

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_startup_lifespan_and_health(self):
        """Verify startup lifespan creates database schema and loads catalogue."""
        with TestClient(self.app) as client:
            resp = client.get("/api/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["database"], "ok")
            self.assertTrue(data["ai_mock_mode"])

    def test_security_headers_present(self):
        """Verify X-Content-Type-Options, Referrer-Policy and X-Request-ID on responses."""
        with TestClient(self.app) as client:
            resp = client.get("/api/health")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.headers.get("Referrer-Policy"), "no-referrer")
            self.assertTrue(resp.headers.get("X-Request-ID", "").startswith("req_"))

    def test_client_config_endpoint(self):
        """Verify client-config returns limits and catalogue-derived component types."""
        with TestClient(self.app) as client:
            resp = client.get("/api/client-config")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["currency"], "INR")
            self.assertEqual(data["currency_symbol"], "₹")
            self.assertIn("component_types", data)
            self.assertTrue(len(data["component_types"]) >= 10)
            # Verify supported is derived from catalogue
            wall_type = next((c for c in data["component_types"] if c["type"] == "wall"), None)
            self.assertIsNotNone(wall_type)
            self.assertTrue(wall_type["supported"])

    def test_unknown_api_route_standard_error(self):
        """Verify unknown routes under /api return standard error response."""
        with TestClient(self.app) as client:
            resp = client.get("/api/unknown/endpoint/path")
            self.assertEqual(resp.status_code, 404)
            data = resp.json()
            self.assertIn("error", data)
            err = data["error"]
            self.assertEqual(err["code"], "NOT_FOUND")
            self.assertIn("endpoint", err["message"])
            self.assertEqual(err["details"].get("resource"), "endpoint")
            self.assertTrue(err["request_id"].startswith("req_"))
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_project_lifecycle_and_navigation_prerequisites(self):
        """Verify project creation establishes initial state for upload placeholder."""
        with TestClient(self.app) as client:
            # 1. Create project
            create_resp = client.post("/api/projects", json={"name": "Suburban Renovation"})
            self.assertEqual(create_resp.status_code, 201)
            project = create_resp.json()
            pid = project["id"]
            self.assertTrue(pid.startswith("prj_"))
            self.assertEqual(project["name"], "Suburban Renovation")
            self.assertEqual(project["last_step"], "upload")
            self.assertEqual(project["photo_count"], 0)
            self.assertEqual(project["component_count"], 0)
            self.assertEqual(project["variant_count"], 1)

            # 2. Get project details
            get_resp = client.get(f"/api/projects/{pid}")
            self.assertEqual(get_resp.status_code, 200)
            self.assertEqual(get_resp.json()["id"], pid)

            # 3. Patch project step
            patch_resp = client.patch(
                f"/api/projects/{pid}",
                json={"name": "Renovated Villa", "last_step": "components"},
            )
            self.assertEqual(patch_resp.status_code, 200)
            self.assertEqual(patch_resp.json()["name"], "Renovated Villa")
            self.assertEqual(patch_resp.json()["last_step"], "components")

            # 4. List projects
            list_resp = client.get("/api/projects")
            self.assertEqual(list_resp.status_code, 200)
            self.assertGreaterEqual(list_resp.json()["total"], 1)

            # 5. Delete project
            del_resp = client.delete(f"/api/projects/{pid}")
            self.assertEqual(del_resp.status_code, 204)

            # 6. Verify 404 in standard error format
            get_again = client.get(f"/api/projects/{pid}")
            self.assertEqual(get_again.status_code, 404)
            err = get_again.json()
            self.assertEqual(err["error"]["code"], "NOT_FOUND")
            self.assertEqual(err["error"]["details"]["resource"], "project")

    def test_validation_error_format(self):
        """Verify 422 errors return standard error format."""
        with TestClient(self.app) as client:
            resp = client.post("/api/projects", json={"name": "   "})
            self.assertEqual(resp.status_code, 422)
            data = resp.json()
            self.assertIn("error", data)
            self.assertEqual(data["error"]["code"], "VALIDATION_ERROR")
            self.assertIn("fields", data["error"]["details"])

    def test_static_index_serving(self):
        """Verify frontend index.html is served at root /."""
        with TestClient(self.app) as client:
            resp = client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("<title>Exterior Renovation Planner</title>", resp.text)


if __name__ == "__main__":
    unittest.main()
