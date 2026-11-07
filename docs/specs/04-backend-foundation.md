# 04 - Backend Foundation

**Purpose:** the common backend infrastructure: application entry point, folder and module architecture, router and service organization, configuration, database and file-storage access, validation, error handling, logging, CORS and basic security. Feature specs own their endpoints and business logic; this file owns only what they all share.
**Depends on:** `01-data-model.md`, `02-api-contracts.md`.
**Used by:** `05` through `12`.

---

## 1. Decisions

| Topic | Decision |
|-------|----------|
| Application | One FastAPI application, one process, no microservices, no background workers |
| Data access | Python standard-library `sqlite3` with parameterized SQL in thin repository modules. No ORM. |
| Schemas | Pydantic models for request/response validation (ships with FastAPI) |
| Frontend serving | The same app serves the `frontend/` folder as static files at `/` |
| Libraries for images, AI and PDF | Chosen in `05`, `06`, `12`; this file does not select them |
| Async model | Route handlers that call AI or do heavy image work run in the thread pool (declared as ordinary functions), so slow calls do not block other users |

## 2. Repository layout

```
project-root/
  backend/
    app/
      main.py                  app factory, middleware, router registration, startup/shutdown
      core/
        config.py              settings loading and validation
        database.py            connection helper, schema creation, transaction helper
        storage.py             file storage helper
        errors.py              application exception types and handlers
        logging_setup.py       log configuration and request-id middleware
        ids.py                 prefixed ID generation
        timeutil.py            UTC timestamp helpers
      api/                     routers: thin HTTP layer only
        deps.py                shared dependencies (db connection, settings, project lookup)
        system.py              /api/health, /api/client-config, /api/projects/{id}/stage-runs
        projects.py            (06)
        photos.py              (06)
        detection.py           (07)
        components.py          (08)
        catalogue.py           (09)
        variants.py            (09)
        generations.py         (10)
        estimation.py          (11) measurements, rates, estimate
        reports.py             (12)
      schemas/                 Pydantic request/response models, one file per router
      services/                business logic, no HTTP types
        ai/                    (05) provider clients, shared AI helpers
        project_service.py
        upload_service.py
        detection_service.py
        component_service.py
        catalogue_service.py
        variant_service.py
        redesign_service.py
        measurement_service.py
        cost_service.py        pure calculation functions, no database access
        report_service.py
      repositories/            SQL access, one module per table group
      data/
        catalogue.json         (09)
    tests/
    .env.example
    requirements.txt           (pinned versions, created at implementation time)
  frontend/                    see 03
  storage/                     runtime files (gitignored)
  data/                        runtime SQLite file (gitignored)
  README.md                    (13)
```

### Layer rules

| Layer | May do | Must not |
|-------|--------|---------|
| `api/` (routers) | Parse request, call one service function, return the schema, declare the route and tags | Contain business rules, SQL, or provider calls |
| `services/` | Business logic, orchestration across repositories, storage and AI helpers; raise application exceptions | Import FastAPI types or build HTTP responses |
| `repositories/` | Execute SQL for one table group; map rows to plain dicts | Contain business rules or call services |
| `core/` | Shared infrastructure | Import from `api/`, `services/` or `repositories/` |
| `cost_service.py` | Pure functions on plain inputs (no I/O, no database) so it is unit-testable | Read config or touch the database |

Dependency direction: `api` -> `services` -> `repositories` -> `core`. Never the reverse.

## 3. Application entry and lifecycle (`main.py`)

**Creation.** One `create_app()` function builds the app, so tests can create instances with different settings.

**Startup sequence** (any failure stops the server with a clear log message):
1. Load and validate settings (section 4). Fail fast on invalid or missing required values.
2. Configure logging.
3. Create the storage root and database directory if missing.
4. Open the database, apply pragmas, create tables if missing, verify `schema_version` (section 5).
5. Load and validate the catalogue file (`09` defines validation). A malformed catalogue stops startup.
6. Sweep interrupted work: mark `stage_runs` and `generations` that are `running` and older than the longest AI timeout as `failed` with `error_code = "INTERRUPTED"`.
7. Register middleware, exception handlers, routers, then mount static files.

**Shutdown.** Close any open resources; nothing else is required.

**Route registration order.** API routers first (all under `/api`), then the static mount at `/` last, so static files never shadow API routes. `GET /` serves `frontend/index.html`.

**Router registration pattern.** Each router module exposes one `router` object with a fixed prefix and a tag. `main.py` imports and includes them in the order of the layout above. Adding a feature means adding one router module and one line in `main.py`.

**Auto documentation.** FastAPI's interactive docs remain enabled in development (`APP_ENV=development`) and disabled when `APP_ENV=production`.

## 4. Configuration (`core/config.py`)

All configuration comes from environment variables, optionally loaded from a `.env` file in `backend/`. One immutable settings object is created at startup and passed via dependency. No module reads environment variables directly.

### 4.1 Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | `development` or `production` |
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8000` | Port |
| `DATABASE_PATH` | `data/app.db` | SQLite file |
| `STORAGE_ROOT` | `storage` | Root for images and reports (`01` section 6) |
| `CATALOGUE_PATH` | `backend/app/data/catalogue.json` | Catalogue file |
| `FRONTEND_DIR` | `frontend` | Static files directory |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Comma-separated CORS origins |
| `MAX_UPLOAD_MB` | `10` | Upload size limit |
| `ALLOWED_IMAGE_TYPES` | `image/jpeg,image/png,image/webp` | Accepted MIME types (verified by content) |
| `MIN_IMAGE_SHORT_SIDE_PX` | `600` | Minimum short side of an uploaded image |
| `MAX_PHOTOS_PER_PROJECT` | `1` | Allowed range 1-3 |
| `MAX_IMAGE_PIXELS` | `40000000` | Maximum decoded pixel count for an uploaded image |
| `MAX_COMPONENTS_PER_PHOTO` | `60` | Maximum working components for one photo |
| `CURRENCY` | `INR` | Currency code used in estimates and reports |
| `CURRENCY_SYMBOL` | `₹` | Display symbol |
| `GEMINI_API_KEY` | none | Google Gemini API key. Required unless mock mode is on. |
| `GEMINI_VISION_MODEL` | none (required unless mock) | Model identifier for detection and AI-assisted estimates (`05`) |
| `NANO_BANANA_IMAGE_MODEL` | none (required unless mock) | Model identifier for image generation/editing (`05`) |
| `AI_MOCK_MODE` | `false` | When `true`, AI calls return canned data (`05`) |
| `AI_MOCK_SCENARIO` | `ok` | Mock behavior selector, used only when `AI_MOCK_MODE=true` (`05`) |
| `AI_WORKING_IMAGE_MAX_PX` | `1600` | Longest side of images sent to AI models |
| `AI_DETECTION_TIMEOUT_S` | `60` | Detection and AI-estimate timeout |
| `AI_IMAGE_TIMEOUT_S` | `120` | Image generation timeout |
| `AI_MAX_RETRIES` | `1` | Retries for invalid or transient AI failures |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

The frontend timeouts in `03` are the corresponding server timeouts plus 15 seconds; if these values change, `03` section 7 must be updated.

`MAX_IMAGE_PIXELS` and `MAX_COMPONENTS_PER_PHOTO` are shared backend configuration constants owned here; feature specifications reference them and do not redefine them. `AI_MOCK_SCENARIO` is an environment setting owned here and is valid only when mock mode is enabled. Its accepted values and behavior are defined in `05`.

### 4.2 Validation (fail fast at startup)

- If `AI_MOCK_MODE` is false and any of `GEMINI_API_KEY`, `GEMINI_VISION_MODEL` or `NANO_BANANA_IMAGE_MODEL` are empty, the server starts successfully but sets `ai_configured = false`. The health endpoint reports this, and all AI endpoints return `503 AI_NOT_CONFIGURED`. The server does not crash, so the rest of the app remains demonstrable.
- When `AI_MOCK_MODE` is true, `AI_MOCK_SCENARIO` must match one of the values defined in `05`; reject an unknown value at startup with a clear configuration error.
- Numeric values must be within sensible ranges (`MAX_PHOTOS_PER_PROJECT` 1-3, `MAX_IMAGE_PIXELS` and `MAX_COMPONENTS_PER_PHOTO` positive, timeouts at least 5, sizes positive).
- Directories must be creatable and writable.
- `ALLOWED_ORIGINS` must not contain `*` when `APP_ENV=production`.

### 4.3 Secrets

- Keys exist only in environment variables or an untracked `.env`.
- `.env.example` lists every variable above with placeholder values and no real key.
- `.env` and the runtime `data/` and `storage/` directories are in `.gitignore`.
- Settings are never serialized into API responses except the explicit public fields in `GET /api/client-config` and `GET /api/health`.

## 5. Database integration (`core/database.py`)

| Concern | Rule |
|---------|------|
| Connection | One connection per request, opened by a dependency and closed after the response. Row factory returns mapping-style rows. |
| Pragmas on every connection | `foreign_keys = ON`, `journal_mode = WAL`, `busy_timeout = 5000` ms, `synchronous = NORMAL` |
| Schema creation | At startup, execute the `CREATE TABLE IF NOT EXISTS` and index statements derived from `01`. Store `schema_version = 1` in `app_meta`. If a different version is found, stop with a message to delete the database (prototype has no migrations). |
| Transactions | A helper provides a transaction context. A service performing a multi-row change uses exactly one transaction. Commit on success, rollback on any exception. |
| AI calls | Never made while a write transaction is open (keeps the SQLite write lock short). Pattern: read inputs, close transaction, call AI, open a new transaction, write results. |
| SQL safety | Parameterized queries only; no string concatenation of values. Dynamic column names come only from fixed internal lists. |
| Constraint errors | Unique-constraint violations are translated by repositories or services into `ConflictError` (never allowed to become a 500). |
| Concurrency | Multiple users are supported by per-request connections plus WAL mode. There is no shared mutable in-memory state in the backend, apart from the immutable settings and the loaded catalogue. |
| Duplicate-run guard | Starting a generation first checks (inside a transaction) that the project has no `running` generation; if it has, raise `GENERATION_IN_PROGRESS`. |

Repositories receive the connection as an argument. They do not open their own.

## 6. File storage (`core/storage.py`)

A single helper owns all disk access under `STORAGE_ROOT`.

| Function (conceptual) | Behaviour |
|-----------------------|-----------|
| `save_bytes(relative_path, data)` | Writes atomically (temporary file then rename). Creates parent directories. |
| `read_bytes(relative_path)` | Returns bytes; raises `NotFoundError` if missing. |
| `open_for_response(relative_path)` | Returns a file handle or path for streaming responses |
| `delete_file(relative_path)` | Removes if present; ignores missing |
| `delete_project_dir(project_id)` | Removes `projects/{project_id}/` recursively |
| `project_path(project_id, kind, filename)` | Builds a path of the form defined in `01` section 6; `kind` is one of `original`, `generated`, `reports` |

Safety rules:
- Every path is resolved and verified to be **inside** `STORAGE_ROOT`; anything else raises an error (path-traversal protection).
- File names are built only from backend-generated IDs and a fixed extension chosen from the verified image type. Client file names are never used for paths.
- Files are served only through the API endpoints in `02` (which look the path up in the database), never through a public static mount of `storage/`.
- Image responses set `Content-Type` from the stored type, `X-Content-Type-Options: nosniff`, and `Cache-Control: private, max-age=3600`.
- A database row without its file (or the reverse) is tolerated: the endpoint returns `404 NOT_FOUND` and logs a warning.

## 7. Validation (common rules)

- **Request validation** is done by Pydantic models in `schemas/`. Models forbid unknown fields, trim strings, and enforce lengths and numeric ranges stated in `01` and `02`.
- **Path parameters** are validated by format (prefix and 16 hex characters) before any database access; a malformed ID returns `404 NOT_FOUND`, not a 422.
- **Ownership checks** are performed in services: a child entity is always looked up by its own ID **and** its `project_id`. A mismatch is `NOT_FOUND`.
- **Shared validators** (provided in `schemas/common.py`): normalized box, component type, step name, material ID slug, non-negative number, percentage 0-100.
- FastAPI's default 422 response is replaced by the standard error format (section 8).

## 8. Error handling (`core/errors.py`)

### 8.1 Application exceptions

One base exception carrying `code`, `message`, `http_status` and optional `details`. Concrete types map to the codes in `02` section 2:

| Exception | Code(s) |
|-----------|---------|
| `ValidationAppError` | `VALIDATION_ERROR` |
| `NotFoundError` | `NOT_FOUND` (with `details.resource`) |
| `ConflictError` | `CONFLICT`, `PHOTO_LIMIT_REACHED`, `NO_PHOTO`, `NO_COMPONENTS`, `NO_SELECTIONS`, `GENERATION_IN_PROGRESS` |
| `UploadError` | `UPLOAD_INVALID_TYPE`, `UPLOAD_TOO_LARGE`, `UPLOAD_TOO_SMALL`, `UPLOAD_CORRUPT` |
| `CatalogueError` | `MATERIAL_INCOMPATIBLE` |
| `AIError` | `AI_NOT_CONFIGURED`, `AI_TIMEOUT`, `AI_RATE_LIMITED`, `AI_UPSTREAM_ERROR`, `AI_INVALID_RESPONSE`, `AI_CONTENT_BLOCKED` (raised by `05`) |

Services raise these; they never return error dictionaries.

### 8.2 Handlers (registered in `main.py`)

| Handler for | Output |
|-------------|--------|
| Application exceptions | The standard error format with the exception's status, code, message, details, and `request_id` |
| Request validation errors | `VALIDATION_ERROR`, `details.fields` built from the field paths and problems |
| Unknown routes under `/api` | `404 NOT_FOUND` in the standard format |
| Any unexpected exception | Log the full traceback with the request ID; return `500 INTERNAL_ERROR` with the generic message "Something went wrong on our side. Please try again." |

Rules:
- Messages are user-safe: no SQL, file paths, stack traces, provider response bodies or key fragments.
- Provider error text is logged, never returned. `AIError` messages are written by `05` in plain language.
- Every error response includes `request_id`.
- When an operation fails after creating a record (a generation, a stage run), the service updates that record to `failed` with the error code and message before raising, so state is never left `running`.

## 9. Logging (`core/logging_setup.py`)

| Aspect | Rule |
|--------|------|
| Output | Standard output, single-line text with `key=value` pairs: `time level logger request_id message ...` |
| Levels | `INFO` for requests and stage start/finish; `WARNING` for recoverable problems (retry, missing file); `ERROR` for failures; `DEBUG` for payload summaries (dev only) |
| Request ID | Middleware generates `req_` + 12 hex characters per request (or accepts a client `X-Request-ID` if it matches that format), stores it in request context, returns it as `X-Request-ID`, and includes it in every log line of that request |
| Request log line | Method, path (no query values for upload routes), status, duration in ms, project ID if present in the path |
| Stage log lines | `stage`, `project_id`, `stage_run_id`, `status`, `duration_ms`, `error_code` |
| Never logged | API keys, full prompts above 500 characters (truncated), image bytes or base64, full provider responses above 1000 characters (truncated), uploaded file contents |
| Debug record | Detailed per-operation data is stored in `stage_runs.detail_json` (`01`), not in logs; `GET /api/projects/{id}/stage-runs` exposes it for debugging |

## 10. CORS and basic API security

| Topic | Rule |
|-------|------|
| CORS | Enabled with the `ALLOWED_ORIGINS` allowlist, methods `GET, POST, PUT, PATCH, DELETE, OPTIONS`, headers `Content-Type, X-Request-ID`, no credentials. Same-origin use needs no CORS; the allowlist exists for local development with a separate frontend server. |
| Authentication | None in the prototype. Access control is the unguessable project ID (64 bits of randomness). This is documented as a limitation; it is not suitable for sensitive data. |
| Project listing | `GET /api/projects` lists all projects on the instance (single-tenant demo). Documented limitation; a per-browser filter by locally remembered IDs is an optional frontend convenience. |
| API key exposure | The Gemini key stays on the server. The frontend never receives it and never calls Google directly. |
| Uploads | Size enforced while reading (reject as soon as the limit is exceeded); type verified by decoding the image, not by extension or declared MIME; dimensions checked; EXIF orientation applied; metadata (including GPS) is not copied into generated images or reports. |
| Response headers | `X-Content-Type-Options: nosniff` on all responses; `Referrer-Policy: no-referrer`. |
| Input injection | Parameterized SQL; user text (labels, notes, extra instructions) is length-limited, stored as plain text, HTML-escaped by the frontend when rendered, and inserted into prompts only inside clearly delimited sections (`10`). |
| Prompt abuse | `extra_instructions` is limited to 500 characters. No other free text is sent to the image model. |
| Rate limiting | Out of scope. Mitigation: one running generation per project, and provider limits surfaced as `AI_RATE_LIMITED`. |
| Dependencies | Versions pinned in `requirements.txt` at implementation time. |

## 11. Shared dependencies (`api/deps.py`)

| Dependency | Provides |
|------------|---------|
| `get_settings` | The immutable settings object |
| `get_db` | A connection for the request, closed afterwards |
| `get_catalogue` | The loaded, validated catalogue (immutable, loaded at startup) |
| `get_project` | Project row by path ID, or `NotFoundError` |
| `get_request_id` | Current request ID |

Routers use these and pass plain values to services.

## 12. Cross-cutting backend rules

1. **Touch rule.** Any service that changes project data updates `projects.updated_at` in the same transaction.
2. **Idempotent deletes.** Deleting an entity that does not exist returns `404`; deleting twice is not an error condition the client must handle specially.
3. **Stage run lifecycle.** For `detection`, `redesign`, `ai_estimate` and `report`, create a `stage_runs` row (`running`) before work, update to `succeeded` or `failed` after, with `duration_ms` and a summarized `detail_json`.
4. **Time source.** All timestamps are created through `timeutil` in UTC.
5. **IDs.** All IDs are created through `ids` with the prefixes in `01`.
6. **Catalogue immutability.** The catalogue is loaded once at startup and treated as read-only. Changing it requires a restart.
7. **Testability.** `create_app()` accepts a settings object, so tests use a temporary database, temporary storage and `AI_MOCK_MODE=true`. `cost_service` has unit tests that need no database.

## 13. Acceptance criteria

- `GET /api/health` returns `ok` after startup with a fresh database; the database file and storage root are created automatically.
- Starting with invalid configuration (e.g. `MAX_PHOTOS_PER_PROJECT=9`) stops the server with a clear message naming the variable.
- Starting with no API key and `AI_MOCK_MODE=false` starts the server, `/api/health` shows `ai_configured: false`, and an AI endpoint returns `503 AI_NOT_CONFIGURED`.
- A request with an invalid body returns the standard error format with `VALIDATION_ERROR` and per-field details.
- A forced exception inside a service returns `INTERNAL_ERROR` with no internals, while the log contains the traceback and the same `request_id` that the response carries.
- A path such as `../../etc/passwd` supplied anywhere cannot read or write outside `STORAGE_ROOT`.
- After a simulated crash mid-generation, restarting marks the generation `failed` with `INTERRUPTED`.
- No log line and no API response contains the API key.
- Two projects can be used from two browser tabs simultaneously without errors.
- Adding a new router requires changes only in its own module and one registration line in `main.py`.
