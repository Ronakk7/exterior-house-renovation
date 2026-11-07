# Exterior House Renovation & Cost Estimation

A local-first web application for planning exterior renovation from a clear exterior photograph or 3D architectural rendering: review detected regions, compare catalogue materials, generate an AI preview, estimate costs deterministically, and produce a PDF discussion report. It is a single FastAPI application with a vanilla JavaScript frontend, SQLite, and local file storage.

## Features

- Upload and technically validate house photographs or 3D architectural renderings; edit or draw component regions.
- Select compatible catalogue materials and save design variants.
- Generate and compare a redesign preview while preserving user-selected regions and scene details.
- Enter approximate measurements, optionally request AI-assisted measurements, and edit rates.
- Calculate quantities and costs in Python; generate and download a PDF report.
- Run the complete workflow with mocked AI and no API key.

## Requirements

- Python 3.11 or newer.
- Windows PowerShell for the commands below (other platforms can use equivalent commands).
- A Google Gemini API key only for live model calls. The application and automated tests work in mock mode without one.

## Windows setup

Run these commands from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
```

By default, the example file is configured for the documented Gemini model IDs but has no key and disables mock mode. To use the app without a key, edit `backend\.env` and set:

```dotenv
AI_MOCK_MODE=true
AI_MOCK_SCENARIO=ok
```

For live Gemini calls, set `GEMINI_API_KEY` on the backend only, set `AI_MOCK_MODE=false`, and configure `GEMINI_VISION_MODEL` and `NANO_BANANA_IMAGE_MODEL`. The current example values are `gemini-3.8-flash` and `gemini-3.1-flash-image`; model availability must be verified for the account and API surface in use. Never put the key in frontend code, browser configuration, screenshots, or source control.

## Run locally

Start the development server from the repository root:

```powershell
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Open <http://127.0.0.1:8000/>. The health endpoint is <http://127.0.0.1:8000/api/health>. Interactive API documentation is available at `/docs` in development and disabled in production.

## End-to-end use

1. Create a project and upload a clear exterior photograph or 3D architectural rendering of your house.
2. Detect regions, then rename, resize, redraw, add, or remove regions as needed. User-corrected regions are protected during re-detection.
3. Choose a material for each supported region; optionally set a paint/texture colour and create named design variants.
4. Generate a redesign preview, compare it with the original, review the result, and approve or regenerate it.
5. Add approximate dimensions, direct areas, or railing lengths. User values remain editable; optional AI-assisted values are labelled.
6. Review the recomputed estimate and warnings, adjusting project rates where needed.
7. Generate and download a PDF report for discussion with a contractor.

## Architecture

The application has one FastAPI process serving both `/api/...` endpoints and the static frontend. Backend services coordinate parameterized SQLite repositories, secure local storage, and AI integrations. The browser uses pure HTML, CSS, and vanilla ES modules; there is no frontend build step or secondary service.

See [docs/architecture.md](docs/architecture.md) for the high-level system and end-to-end data-flow Mermaid diagrams.

The Vision call uses the configured Gemini model to interpret the original exterior image (photograph or rendering) for component detection and optional approximate measurements. The detector accepts clear exterior renderings and does not reject them solely because they are computer-generated. The separate Nano Banana image-generation call uses the original image and selected material instructions to create a visual preview. Neither model computes financial totals. The Python `cost_service` calculates the estimate, and ReportLab renders the report from the same estimate service.

## Estimation methodology

The estimate is approximate and recomputed on each request. For surface components, gross area is entered directly or calculated from width × height; opening deductions are subtracted and the result is clamped at zero. Railing quantities use length. Wastage is applied to material quantity; material cost uses the quantity including wastage, while labour uses installed quantity. Purchase quantities use catalogue coverage where available. Costs use Python `Decimal` arithmetic and the specified half-up currency rounding. Measurement uncertainty produces low/high ranges; missing or incompatible measurements are excluded and reported. Rates and wastage can be overridden per project. AI-derived measurements are labeled approximate and editable. A rendering has no verified physical scale: dimensions inferred from it are not verified measurements and must be checked against a known scale or on site. Catalogue rates are starter placeholders, not a local quotation.

## Configuration

Settings are read by the backend from `backend\.env` or the process environment. The settings object is validated and immutable after startup.

| Variable | Default | Purpose |
|---|---:|---|
| `APP_ENV` | `development` | `development` enables API docs; use `production` for deployment. |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Bind values to pass to Uvicorn when starting the server. |
| `WEENY_DATA_DIR` | unset | When set, stores SQLite at `<dir>/app.db` and all uploaded/generated files under `<dir>/storage`; the app creates these directories automatically. |
| `DATABASE_PATH` | `data/app.db` | SQLite database path for local use; `WEENY_DATA_DIR` takes precedence when set. |
| `STORAGE_ROOT` | `storage` | Local storage path for uploads, generated images, and PDFs; `WEENY_DATA_DIR` takes precedence when set. |
| `CATALOGUE_PATH` | `backend/app/data/catalogue.json` | Validated material catalogue. |
| `FRONTEND_DIR` | `frontend` | Static frontend directory. |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Comma-separated CORS origins; use exact trusted origins in production. |
| `MAX_UPLOAD_MB` | `10` | Maximum upload size in MB. |
| `ALLOWED_IMAGE_TYPES` | `image/jpeg,image/png,image/webp` | Accepted image types, verified from content. |
| `MIN_IMAGE_SHORT_SIDE_PX` | `600` | Minimum decoded image short side. |
| `MAX_PHOTOS_PER_PROJECT` | `1` | Photo count limit (configurable from 1 to 3). |
| `MAX_IMAGE_PIXELS` | `40000000` | Maximum decoded image pixel count. |
| `MAX_COMPONENTS_PER_PHOTO` | `60` | Maximum working regions on one photo. |
| `CURRENCY`, `CURRENCY_SYMBOL` | `INR`, `₹` | Currency for estimates and reports. |
| `GEMINI_API_KEY` | unset | Backend-only key; required for live AI, not for mock mode. |
| `GEMINI_VISION_MODEL` | unset | Vision model ID; configured example: `gemini-3.8-flash`. |
| `NANO_BANANA_IMAGE_MODEL` | unset | Image model ID; configured example: `gemini-3.1-flash-image`. |
| `AI_MOCK_MODE` | `false` | Use deterministic mock AI responses when `true`. |
| `AI_MOCK_SCENARIO` | `ok` | Mock case such as `ok`, `unusable`, `invalid_json`, `timeout`, or `rate_limited`. |
| `AI_WORKING_IMAGE_MAX_PX` | `1600` | Maximum long edge sent to AI. |
| `AI_DETECTION_TIMEOUT_S` | `60` | Vision-operation timeout. |
| `AI_IMAGE_TIMEOUT_S` | `120` | Image-generation timeout. |
| `AI_MAX_RETRIES` | `1` | Retry count for eligible Vision failures. |
| `LOG_LEVEL` | `INFO` | Backend log level. |

For exact validation rules and additional context, see [04-backend-foundation.md](docs/specs/04-backend-foundation.md) and [05-ai-integration.md](docs/specs/05-ai-integration.md).

## Automated tests

Run both existing test suites from the repository root:

```powershell
python -m unittest discover -s backend\tests
node --test frontend\tests
```

The Python suite uses `unittest`; the frontend suite uses Node.js's built-in `node:test`. AI calls are mocked in automated tests. No `pytest` migration, Node package installation, or frontend build is required.

The regression suite verifies that photographs and rendered-exterior fixtures continue through detection, material selection, measurement, and estimation, while interior/floor-plan and blurry-image responses remain unusable. A single live Gemini Vision smoke test on a CC BY 4.0 3D exterior rendering from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Contemporary_Residence_with_Gable_Windows_%E2%80%93_3D_Architectural_Visualization.jpg) returned `usable: true` with 12 detected components; this is an integration smoke check, not broad real-image acceptance testing.

## Data, privacy, and limitations

- SQLite and uploaded/generated files are local runtime data. Back up the database and the corresponding storage directory together.
- With live AI enabled, original photographs/renderings or working-image derivatives are sent to Google's Gemini service for the requested Vision or image-generation operation. Do not upload images without the necessary rights or consent; review Google's applicable data policies.
- The prototype has no user accounts or project-level authorization. Projects on a shared instance are not private from other users of that instance.
- Redesign structure preservation is prompt-based, not guaranteed, and must be visually checked by a person.
- Regions are rectangular boxes, not segmentation masks. Perspective, depth, and curved surfaces are not reconstructed.
- The default is one exterior image per project. Both photographs and clear CGI/rendered exteriors are accepted; multi-view measurement and verified physical-scale inference from renderings are not implemented.
- Re-detection protects locked user-edited/drawn components, but unlocked regions can be replaced and related selections or AI measurements may be invalidated.
- AI-assisted dimensions are approximate and must be checked on site. A generated redesign is never used for measurement.
- Starter catalogue prices and coverage are placeholders. Estimates exclude items described in the estimate and report assumptions; they are not contractor quotations.
- Standard PDF fonts have limited character support. Unsupported characters are sanitized, and INR amounts use the `INR` code rather than relying on a rupee glyph.
- No automated structural verification, authentication, rate limiting, segmentation, 3D reconstruction, or multi-photo workflow is provided.

## Clean local database without deleting existing data

To start with a fresh project store while preserving any current database and uploaded files, set distinct paths in `backend\.env`:

```dotenv
DATABASE_PATH=data/clean-demo.db
STORAGE_ROOT=storage/clean-demo
```

Restart the app. It creates a new database and storage subtree; existing `data\app.db` and `storage\projects` remain untouched. Do not remove runtime data to reset a project.

## Packaging and data safety

Do not include `.env` files, API keys, `.venv`, Python caches/bytecode, temporary test output, the runtime SQLite database, or runtime storage in a submission archive. The repository ignore rules exclude these local files; the catalogue and `.env.example` are safe source assets. Do not delete `data\app.db` or `storage\projects` when preparing a clean demo—use the separate paths above instead. No archive is required to run the application.

## Deployment readiness

A private assessment deployment is running on the existing Weeny Cloud free server. The FastAPI process binds to `127.0.0.1:8000`; Weeny terminates HTTPS and requires Weeny sign-in for the app. Unauthenticated requests were verified to receive HTTP 401. The app itself does not implement authentication, so do not remove Weeny's private access gate or make the app public without adding and verifying an equivalent access-control layer.

The deployment uses `APP_ENV=production`, `AI_MOCK_MODE=false`, and encrypted Weeny app configuration for the Gemini key and model IDs. The key is not part of the release or frontend. `WEENY_DATA_DIR=/data/exterior-renovation` keeps SQLite at `/data/exterior-renovation/app.db` and uploaded originals, generated redesigns, and PDF reports under `/data/exterior-renovation/storage`; startup creates the directories automatically. Weeny releases and rollbacks keep this data directory separate from application code.

The free server may sleep after inactivity and wake on a later request. The free server tier does not include Gemini API usage; live Vision and image-generation requests may incur separate Google charges. This private demo deployment is not a public production-readiness certification. Before public or broader deployment, review authentication/authorization, rate limiting, operational monitoring, backup/restore, CORS origins, and API spending controls. CORS is not access protection.

## Project layout

```text
backend/app/       FastAPI routers, core infrastructure, SQLite repositories, services
backend/tests/     unittest integration and unit tests
frontend/          Static HTML, CSS, and vanilla ES modules
docs/specs/        Approved specifications 00–14
docs/architecture.md
data/              Runtime SQLite database (ignored by Git)
storage/            Runtime photos, generated images, and PDFs (ignored by Git)
```

The project specifications describe the system and delivery process; they are not runtime instructions. Future work may include authentication, multi-photo/perspective support, segmentation, automated structure verification, and regional pricing data.
