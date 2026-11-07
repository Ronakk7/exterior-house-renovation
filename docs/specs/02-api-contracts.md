# 02 - API Contracts

**Purpose:** every endpoint, its request and response shape, status codes and the single error format. Business rules live in the feature specs; this file defines the interface.
**Depends on:** `01-data-model.md`.
**Used by:** `03` (frontend), `04` (backend), and all feature specs.

---

## 1. Conventions

| Topic | Rule |
|-------|------|
| Base path | All API routes start with `/api`. The frontend is served from `/`. |
| Format | JSON in and out (`application/json`), except uploads (`multipart/form-data`) and file downloads. |
| Field naming | `snake_case`, identical to the database field names in `01` wherever the concept is the same. |
| IDs | Strings as defined in `01` (`prj_...`). |
| Timestamps | ISO 8601 UTC with `Z`. |
| Boxes | `{ "x": 0.12, "y": 0.30, "w": 0.25, "h": 0.40 }`, normalized 0-1, origin top-left. In `01` these are `box_x, box_y, box_w, box_h`. |
| Success bodies | The resource directly (no wrapper). Lists are `{ "items": [ ... ] }`. |
| Empty success | `204 No Content` for deletes. |
| Unknown request fields | Rejected with `VALIDATION_ERROR`. |
| Money | JSON numbers, currency from `GET /api/client-config`, rounded to 2 decimals by the server. |
| Slow operations | Detection, redesign and AI estimate are **synchronous** requests. They return when finished. The frontend shows a busy indicator and uses a client timeout 15 s longer than the server timeout (`05`). |
| Versioning | No version prefix in the prototype. |
| Authentication | None. The project ID is the only access key. See `04` for security notes. |

## 2. Error format (all errors)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message safe to show to the user.",
    "details": { },
    "request_id": "req_ab12cd34ef56"
  }
}
```

- `code`: stable machine-readable string from the table below.
- `message`: plain language, no stack traces, no internal paths, no secrets.
- `details`: optional object. Validation errors use `{"fields": [{"field": "name", "problem": "must be 1-100 characters"}]}`.
- `request_id`: matches the `X-Request-ID` response header and the server log.

### Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `VALIDATION_ERROR` | 422 | Request body, path or query is invalid |
| `NOT_FOUND` | 404 | Entity does not exist. `details.resource` names it (e.g. `project`). |
| `CONFLICT` | 409 | Uniqueness or state conflict (duplicate variant name, deleting the last variant, etc.). `details.reason` gives a short slug. |
| `UPLOAD_INVALID_TYPE` | 415 | File is not a supported image (checked by content, not extension) |
| `UPLOAD_TOO_LARGE` | 413 | File exceeds `MAX_UPLOAD_MB` |
| `UPLOAD_TOO_SMALL` | 422 | Image resolution below the minimum short side |
| `UPLOAD_CORRUPT` | 422 | File could not be decoded |
| `PHOTO_LIMIT_REACHED` | 409 | Project already has `MAX_PHOTOS_PER_PROJECT` photos |
| `NO_PHOTO` | 409 | Operation needs a photo and none exists |
| `NO_COMPONENTS` | 409 | Operation needs components and none exist |
| `NO_SELECTIONS` | 409 | Redesign requested for a variant with no selections |
| `MATERIAL_INCOMPATIBLE` | 422 | Material is unknown or not compatible with the component type |
| `GENERATION_IN_PROGRESS` | 409 | A generation is already running for this project |
| `AI_NOT_CONFIGURED` | 503 | API key missing and mock mode is off |
| `AI_TIMEOUT` | 504 | The AI call exceeded its timeout |
| `AI_RATE_LIMITED` | 429 | Provider rate or quota limit reached |
| `AI_UPSTREAM_ERROR` | 502 | Provider returned an error |
| `AI_INVALID_RESPONSE` | 502 | Provider output could not be parsed or validated after retry |
| `AI_CONTENT_BLOCKED` | 422 | Provider refused or filtered the request or result |
| `INTERRUPTED` | n/a | Recorded on stage runs/generations marked failed after a restart; not returned by endpoints |
| `INTERNAL_ERROR` | 500 | Unexpected error. Message is generic. |

## 3. Shared object shapes

### 3.1 Project

```json
{
  "id": "prj_0123456789abcdef",
  "name": "My house",
  "last_step": "components",
  "active_variant_id": "var_...",
  "floor_count": 2,
  "photo_count": 1,
  "component_count": 14,
  "variant_count": 2,
  "created_at": "2026-11-06T09:30:00Z",
  "updated_at": "2026-11-06T09:45:00Z"
}
```
`photo_count`, `component_count`, `variant_count` are derived. `floor_count` may be null.

### 3.2 Photo

```json
{
  "id": "pho_...",
  "project_id": "prj_...",
  "view_index": 1,
  "facade_label": null,
  "original_filename": "house.jpg",
  "mime_type": "image/jpeg",
  "width_px": 1600,
  "height_px": 1200,
  "file_size_bytes": 845120,
  "quality_usable": true,
  "quality_reason": null,
  "detected_at": "2026-11-06T09:35:00Z",
  "image_url": "/api/projects/prj_.../photos/pho_.../image",
  "created_at": "2026-11-06T09:31:00Z"
}
```
`quality_usable` and `detected_at` are null before detection.

### 3.3 Component

```json
{
  "id": "cmp_...",
  "project_id": "prj_...",
  "photo_id": "pho_...",
  "type": "wall",
  "label": "left wall, ground floor",
  "box": { "x": 0.05, "y": 0.4, "w": 0.3, "h": 0.5 },
  "confidence": 0.86,
  "origin": "ai",
  "is_locked": false,
  "supported": true,
  "created_at": "...",
  "updated_at": "..."
}
```
`supported` is derived from the catalogue (`01`, section 5). `confidence` is null for user-created components.

### 3.4 Material (catalogue entry; full semantics in `09`)

```json
{
  "id": "paint_emulsion_matte",
  "name": "Matte emulsion paint",
  "category": "paint",
  "compatible_types": ["wall", "pillar", "parapet", "gate"],
  "pricing_unit": "sqft",
  "purchase_unit": "litre",
  "coverage_per_purchase_unit": 100,
  "default_material_rate": 18.0,
  "default_labour_rate": 12.0,
  "default_wastage_pct": 8,
  "swatch_hex": "#E8DCC8",
  "prompt_description": "smooth matte warm beige emulsion paint",
  "maintenance_note": "Repaint every 5-7 years.",
  "durability_note": "Good; fades under strong sun."
}
```
- `pricing_unit`: `sqft` or `rft` (running feet). Rates are per `pricing_unit`.
- `purchase_unit` and `coverage_per_purchase_unit` may be null when quantity is expressed directly in `pricing_unit`.
- Exact field semantics and examples are owned by `09`; names here are final.

### 3.5 Variant and Selection

```json
{
  "id": "var_...",
  "project_id": "prj_...",
  "name": "Design 1",
  "is_active": true,
  "selections": [
    {
      "component_id": "cmp_...",
      "material_id": "paint_emulsion_matte",
      "params": { "color_hex": "#C8B8A0", "note": "" },
      "updated_at": "..."
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```
`is_active` is derived from `projects.active_variant_id`.

### 3.6 Generation

```json
{
  "id": "gen_...",
  "project_id": "prj_...",
  "variant_id": "var_...",
  "photo_id": "pho_...",
  "status": "succeeded",
  "is_stale": false,
  "is_approved": false,
  "extra_instructions": null,
  "model_name": "configured-model-name",
  "width_px": 1600,
  "height_px": 1200,
  "image_url": "/api/projects/prj_.../generations/gen_.../image",
  "error_code": null,
  "error_message": null,
  "created_at": "...",
  "completed_at": "...",
  "duration_ms": 18400
}
```
`prompt_text` is **not** included in list responses. It is returned only by `GET .../generations/{id}`. `image_url` is null unless `status` is `succeeded`.

### 3.7 Measurement

```json
{
  "component_id": "cmp_...",
  "input_mode": "dimensions",
  "width_ft": 30,
  "height_ft": 10,
  "length_ft": null,
  "area_sqft": 300,
  "deduction_sqft": 40,
  "net_area_sqft": 260,
  "uncertainty_pct": 15,
  "source": "user",
  "note": null,
  "updated_at": "..."
}
```
`area_sqft` and `net_area_sqft` are computed by the server. For `input_mode = "length"`, both are null.

### 3.8 Effective rate

```json
{
  "material_id": "paint_emulsion_matte",
  "material_name": "Matte emulsion paint",
  "pricing_unit": "sqft",
  "material_rate": 18.0,
  "labour_rate": 12.0,
  "wastage_pct": 8,
  "is_overridden": false,
  "defaults": { "material_rate": 18.0, "labour_rate": 12.0, "wastage_pct": 8 }
}
```

### 3.9 Estimate (computed, not stored)

```json
{
  "variant_id": "var_...",
  "currency": "INR",
  "line_items": [
    {
      "component_id": "cmp_...",
      "component_type": "wall",
      "component_label": "left wall, ground floor",
      "material_id": "paint_emulsion_matte",
      "material_name": "Matte emulsion paint",
      "category": "paint",
      "pricing_unit": "sqft",
      "measure_value": 260,
      "measure_unit": "sqft",
      "wastage_pct": 8,
      "quantity_with_wastage": 280.8,
      "purchase_quantity": 3,
      "purchase_unit": "litre",
      "material_cost": 5054.4,
      "labour_cost": 3120.0,
      "line_total": 8174.4,
      "low_total": 6948.24,
      "high_total": 9400.56,
      "measurement_source": "user",
      "uncertainty_pct": 15
    }
  ],
  "category_totals": [
    { "category": "paint", "material_cost": 5054.4, "labour_cost": 3120.0, "total": 8174.4 }
  ],
  "grand_total": 8174.4,
  "grand_total_low": 6948.24,
  "grand_total_high": 9400.56,
  "missing_measurements": [
    { "component_id": "cmp_...", "component_label": "front pillar", "material_name": "Stone cladding" }
  ],
  "disclaimers": [
    "Estimates are approximate and advisory, not a binding quotation."
  ]
}
```
- `measure_value`: net area for `sqft` pricing, length for `rft`.
- `missing_measurements` lists selected components with no measurement; they are excluded from totals and the UI must say so.
- Rounding and formula rules are owned by `11`. The example numbers are illustrative only.

### 3.10 Report

```json
{
  "id": "rep_...",
  "project_id": "prj_...",
  "variant_id": "var_...",
  "generation_id": "gen_...",
  "grand_total": 8174.4,
  "currency": "INR",
  "download_url": "/api/projects/prj_.../reports/rep_.../download",
  "created_at": "..."
}
```

### 3.11 Stage run (debug)

```json
{
  "id": "run_...",
  "stage": "detection",
  "status": "succeeded",
  "started_at": "...",
  "finished_at": "...",
  "duration_ms": 6200,
  "error_code": null,
  "error_message": null,
  "detail": { "model": "configured-model-name", "retries": 0, "component_count": 12 }
}
```

## 4. Endpoint summary

| # | Method | Path | Purpose | Owner spec |
|---|--------|------|---------|-----------|
| 1 | GET | `/api/health` | Liveness and config sanity | 04 |
| 2 | GET | `/api/client-config` | Limits, vocabulary and flags for the frontend | 04 |
| 3 | POST | `/api/projects` | Create project | 06 |
| 4 | GET | `/api/projects` | List projects | 06 |
| 5 | GET | `/api/projects/{project_id}` | Get project | 06 |
| 6 | PATCH | `/api/projects/{project_id}` | Rename, set step, set active variant, set floor count | 06 |
| 7 | DELETE | `/api/projects/{project_id}` | Delete project and files | 06 |
| 8 | POST | `/api/projects/{project_id}/photos` | Upload photo (multipart `file`) | 06 |
| 9 | GET | `/api/projects/{project_id}/photos` | List photos | 06 |
| 10 | GET | `/api/projects/{project_id}/photos/{photo_id}/image` | Original image bytes | 06 |
| 11 | DELETE | `/api/projects/{project_id}/photos/{photo_id}` | Delete photo and dependents | 06 |
| 12 | POST | `/api/projects/{project_id}/photos/{photo_id}/detect` | Run detection | 07 |
| 13 | GET | `/api/projects/{project_id}/components` | List components (`?photo_id=`) | 08 |
| 14 | POST | `/api/projects/{project_id}/components` | Add component | 08 |
| 15 | PATCH | `/api/projects/{project_id}/components/{component_id}` | Edit component | 08 |
| 16 | DELETE | `/api/projects/{project_id}/components/{component_id}` | Delete component | 08 |
| 17 | GET | `/api/catalogue` | Whole catalogue | 09 |
| 18 | GET | `/api/catalogue/materials` | Materials, filter `?component_type=` | 09 |
| 19 | GET | `/api/projects/{project_id}/variants` | List variants with selections | 09 |
| 20 | POST | `/api/projects/{project_id}/variants` | Create or duplicate variant | 09 |
| 21 | PATCH | `/api/projects/{project_id}/variants/{variant_id}` | Rename variant | 09 |
| 22 | DELETE | `/api/projects/{project_id}/variants/{variant_id}` | Delete variant | 09 |
| 23 | PUT | `/api/projects/{project_id}/variants/{variant_id}/selections/{component_id}` | Set selection | 09 |
| 24 | DELETE | `/api/projects/{project_id}/variants/{variant_id}/selections/{component_id}` | Remove selection | 09 |
| 25 | POST | `/api/projects/{project_id}/variants/{variant_id}/generations` | Generate redesign | 10 |
| 26 | GET | `/api/projects/{project_id}/generations` | List generations (`?variant_id=`) | 10 |
| 27 | GET | `/api/projects/{project_id}/generations/{generation_id}` | Get generation (includes `prompt_text`) | 10 |
| 28 | PATCH | `/api/projects/{project_id}/generations/{generation_id}` | Set approval | 10 |
| 29 | DELETE | `/api/projects/{project_id}/generations/{generation_id}` | Delete generation | 10 |
| 30 | GET | `/api/projects/{project_id}/generations/{generation_id}/image` | Generated image bytes | 10 |
| 31 | GET | `/api/projects/{project_id}/measurements` | List measurements | 11 |
| 32 | PUT | `/api/projects/{project_id}/components/{component_id}/measurement` | Set user measurement | 11 |
| 33 | DELETE | `/api/projects/{project_id}/components/{component_id}/measurement` | Remove measurement | 11 |
| 34 | POST | `/api/projects/{project_id}/measurements/ai-estimate` | Gemini-assisted approximate estimates | 11 |
| 35 | GET | `/api/projects/{project_id}/rates` | Effective rates | 11 |
| 36 | PUT | `/api/projects/{project_id}/rates/{material_id}` | Override rates | 11 |
| 37 | DELETE | `/api/projects/{project_id}/rates/{material_id}` | Reset to defaults | 11 |
| 38 | GET | `/api/projects/{project_id}/variants/{variant_id}/estimate` | Computed estimate | 11 |
| 39 | POST | `/api/projects/{project_id}/reports` | Generate PDF | 12 |
| 40 | GET | `/api/projects/{project_id}/reports` | List reports | 12 |
| 41 | GET | `/api/projects/{project_id}/reports/{report_id}/download` | Download PDF | 12 |
| 42 | GET | `/api/projects/{project_id}/stage-runs` | Debug log | 04 |

All path IDs not found return `404 NOT_FOUND`. A path whose project does not own the referenced child (e.g. a component of another project) also returns `404`.

## 5. Endpoint details

### 5.1 System

**GET `/api/health`** returns `200`:
```json
{ "status": "ok", "version": "0.1.0", "database": "ok", "ai_mock_mode": false, "ai_configured": true }
```

**GET `/api/client-config`** returns `200`:
```json
{
  "app_name": "Exterior Renovation Planner",
  "currency": "INR",
  "currency_symbol": "₹",
  "upload": {
    "max_upload_mb": 10,
    "allowed_mime_types": ["image/jpeg", "image/png", "image/webp"],
    "min_short_side_px": 600,
    "max_photos_per_project": 1
  },
  "component_types": [
    { "type": "wall", "label": "Wall", "supported": true },
    { "type": "window", "label": "Window", "supported": false }
  ],
  "limits": { "extra_instructions_max_chars": 500, "project_name_max_chars": 100 },
  "ai_mock_mode": false
}
```
`component_types` is the vocabulary from `01` with display labels; `supported` is derived from the catalogue. The frontend must not hard-code this list.

### 5.2 Projects (spec 06)

| Endpoint | Request | Success | Errors |
|----------|---------|---------|--------|
| POST `/api/projects` | `{ "name": "My house" }` | `201` Project | `VALIDATION_ERROR` |
| GET `/api/projects` | query `?limit=50&offset=0` | `200` `{ "items": [Project], "total": 3 }` ordered by `updated_at` descending | |
| GET `/api/projects/{id}` | | `200` Project | `NOT_FOUND` |
| PATCH `/api/projects/{id}` | any of `name`, `last_step`, `active_variant_id`, `floor_count` | `200` Project | `VALIDATION_ERROR`, `NOT_FOUND` (project, or `active_variant_id` not in project) |
| DELETE `/api/projects/{id}` | | `204` | `NOT_FOUND` |

### 5.3 Photos (spec 06)

**POST `/api/projects/{id}/photos`**: `multipart/form-data` with one field `file`. Returns `201` Photo.
Errors: `UPLOAD_INVALID_TYPE`, `UPLOAD_TOO_LARGE`, `UPLOAD_TOO_SMALL`, `UPLOAD_CORRUPT`, `PHOTO_LIMIT_REACHED`, `NOT_FOUND`.

**GET `.../photos`** returns `{ "items": [Photo] }`.
**GET `.../photos/{photo_id}/image`** returns raw image bytes with the stored `Content-Type` and `Cache-Control: private, max-age=3600`.
**DELETE `.../photos/{photo_id}`** returns `204`; cascades per `01` section 7.2.

### 5.4 Detection (spec 07)

**POST `/api/projects/{id}/photos/{photo_id}/detect`**, no body. Synchronous. Returns `200`:
```json
{
  "stage_run_id": "run_...",
  "photo": { "...Photo with quality_usable, quality_reason, detected_at updated..." },
  "usable": true,
  "quality_reason": null,
  "components": [ "...Component objects, the full current working set for the photo..." ],
  "kept_locked_count": 2,
  "warnings": []
}
```
- If the photo is judged unusable (`usable: false`), the response is still `200`, `components` is the existing working set unchanged, and `quality_reason` carries guidance text. The frontend shows the guidance and offers re-upload.
- Errors: `NOT_FOUND`, `AI_NOT_CONFIGURED`, `AI_TIMEOUT`, `AI_RATE_LIMITED`, `AI_UPSTREAM_ERROR`, `AI_INVALID_RESPONSE`, `AI_CONTENT_BLOCKED`.

### 5.5 Components (spec 08)

| Endpoint | Request | Success | Notes |
|----------|---------|---------|-------|
| GET `.../components?photo_id=` | | `200` `{ "items": [Component] }` | `photo_id` optional; defaults to all photos of the project |
| POST `.../components` | `{ "photo_id", "type", "label"?, "box": {x,y,w,h} }` | `201` Component | Created with `origin: "user"`, `is_locked: true`. `label` defaults to the type's display label. |
| PATCH `.../components/{cid}` | any of `type`, `label`, `box` | `200` `{ "component": Component, "removed_selections": 1, "removed_ai_measurement": false, "warnings": [] }` | Sets `is_locked: true`. Applies the effects in `01` section 7.2. |
| DELETE `.../components/{cid}` | | `204` | Cascades selections and measurement |

Validation: `type` must be in the vocabulary; `box` must satisfy the box constraint (`01`); `label` 1-120 characters. Failures return `VALIDATION_ERROR`.

### 5.6 Catalogue (spec 09)

**GET `/api/catalogue`** returns `200`:
```json
{
  "version": "1",
  "categories": [ { "id": "paint", "name": "Paint" } ],
  "materials": [ "...Material objects..." ],
  "type_map": { "wall": ["paint_emulsion_matte", "stone_cladding_slate"], "railing": ["glass_railing_clear"] }
}
```
**GET `/api/catalogue/materials?component_type=wall`** returns `{ "items": [Material] }` filtered by compatibility. An unknown `component_type` returns `VALIDATION_ERROR`; a known type with no materials returns an empty list.

### 5.7 Variants and selections (spec 09)

| Endpoint | Request | Success | Errors |
|----------|---------|---------|--------|
| GET `.../variants` | | `200` `{ "items": [Variant] }` | |
| POST `.../variants` | `{ "name": "Design 2", "copy_from_variant_id": "var_..."? }` | `201` Variant (selections copied if `copy_from_variant_id` given) | `CONFLICT` (`reason: "duplicate_name"`), `NOT_FOUND` |
| PATCH `.../variants/{vid}` | `{ "name" }` | `200` Variant | `CONFLICT`, `VALIDATION_ERROR` |
| DELETE `.../variants/{vid}` | | `204`. If it was active, the oldest remaining variant becomes active. | `CONFLICT` (`reason: "last_variant"`) |
| PUT `.../variants/{vid}/selections/{cid}` | `{ "material_id": "...", "params": { "color_hex"?, "note"? } }` | `200` Selection object (shape in 3.5) | `MATERIAL_INCOMPATIBLE`, `NOT_FOUND`, `VALIDATION_ERROR` |
| DELETE `.../variants/{vid}/selections/{cid}` | | `204` | `NOT_FOUND` |

PUT is an upsert: it replaces the existing selection for that component in that variant.

### 5.8 Generations (spec 10)

**POST `/api/projects/{id}/variants/{vid}/generations`**

Request (all optional):
```json
{ "photo_id": "pho_...", "extra_instructions": "keep the garden unchanged" }
```
`photo_id` defaults to the project's photo with `view_index` 1. `extra_instructions` max 500 characters.

Behaviour: synchronous. Success returns `201` Generation with `status: "succeeded"`.
Errors: `NO_PHOTO`, `NO_COMPONENTS`, `NO_SELECTIONS`, `GENERATION_IN_PROGRESS`, `AI_NOT_CONFIGURED`, `AI_TIMEOUT`, `AI_RATE_LIMITED`, `AI_UPSTREAM_ERROR`, `AI_INVALID_RESPONSE`, `AI_CONTENT_BLOCKED`.
On any AI error after the generation row was created, the row is stored as `failed` and the error response includes `details.generation_id` so the frontend can show it in history.

| Endpoint | Request | Success |
|----------|---------|---------|
| GET `.../generations?variant_id=` | | `200` `{ "items": [Generation] }` newest first; `is_stale` computed |
| GET `.../generations/{gid}` | | `200` Generation plus `prompt_text` |
| PATCH `.../generations/{gid}` | `{ "is_approved": true }` | `200` Generation. Approving clears approval on other generations of the same variant. Only `succeeded` generations can be approved (`CONFLICT`, `reason: "not_succeeded"`). |
| DELETE `.../generations/{gid}` | | `204` (removes the file) |
| GET `.../generations/{gid}/image` | | Raw `image/png` bytes; `404` unless succeeded |

### 5.9 Measurements and rates (spec 11)

**GET `.../measurements`** returns `{ "items": [Measurement] }` for all components of the project that have one.

**PUT `.../components/{cid}/measurement`** request:
```json
{
  "input_mode": "dimensions",
  "width_ft": 30,
  "height_ft": 10,
  "deduction_sqft": 40,
  "uncertainty_pct": 15,
  "note": "approx, paced out"
}
```
- `input_mode = dimensions`: requires `width_ft`, `height_ft`.
- `input_mode = area`: requires `area_sqft`.
- `input_mode = length`: requires `length_ft`.
- `deduction_sqft` (default 0) and `uncertainty_pct` (default 15) optional. Fields not belonging to the mode are ignored and stored as null.
- Always stored with `source: "user"`. Returns `200` Measurement.
- Errors: `VALIDATION_ERROR`, `NOT_FOUND`.

**DELETE `.../components/{cid}/measurement`** returns `204`.

**POST `.../measurements/ai-estimate`** request (all optional):
```json
{
  "component_ids": ["cmp_..."],
  "reference_note": "the front door is about 7 ft tall",
  "floor_count": 2
}
```
Behaviour: synchronous Gemini call. If `floor_count` is provided in the request, it takes precedence over the stored `projects.floor_count` for this call. Estimates only components that (a) are selected in any variant or listed in `component_ids`, and (b) have no measurement. Returns `200`:
```json
{
  "stage_run_id": "run_...",
  "items": [ "...Measurement objects with source: ai_estimate..." ],
  "skipped": [ { "component_id": "cmp_...", "reason": "has_measurement" } ],
  "disclaimer": "AI-assisted visual estimates are approximate. Please check and edit them."
}
```
Errors: `NO_PHOTO`, `NO_COMPONENTS`, and the `AI_*` codes.

**Rates:**

| Endpoint | Request | Success |
|----------|---------|---------|
| GET `.../rates` | | `200` `{ "items": [EffectiveRate] }` for all catalogue materials |
| PUT `.../rates/{material_id}` | any of `material_rate`, `labour_rate`, `wastage_pct` (numbers >= 0; wastage 0-50; null clears that field) | `200` EffectiveRate. Errors: `MATERIAL_INCOMPATIBLE` (unknown material), `VALIDATION_ERROR` |
| DELETE `.../rates/{material_id}` | | `204` |

### 5.10 Estimate (spec 11)

**GET `.../variants/{vid}/estimate`** returns `200` Estimate (3.9). Never errors for missing data: missing pieces are reported in `missing_measurements`. If the variant has no selections, `line_items` is empty and `grand_total` is 0.

### 5.11 Reports (spec 12)

**POST `/api/projects/{id}/reports`** request:
```json
{ "variant_id": "var_...", "generation_id": "gen_..." }
```
- `variant_id` defaults to the project's active variant.
- `generation_id` optional; if omitted, the approved generation of the variant is used, else the newest succeeded one, else the report is produced without a redesigned image and says so.
- Returns `201` Report. Errors: `NOT_FOUND`, `NO_PHOTO`, `NO_COMPONENTS`, `NO_SELECTIONS`.

**GET `.../reports`** returns `{ "items": [Report] }`. **GET `.../reports/{rid}/download`** returns `application/pdf` with `Content-Disposition: attachment; filename="renovation-report-{project name slug}.pdf"`.

### 5.12 Stage runs (debug)

**GET `/api/projects/{id}/stage-runs?stage=detection`** returns `{ "items": [StageRun] }` newest first, max 50.

## 6. Frontend-facing guarantees

- Every endpoint that changes data returns the updated resource, so the frontend can refresh state without an extra call, except `204` deletes.
- Changing components, selections, measurements or rates never needs a manual "recalculate" call: `GET .../estimate` always reflects current data.
- Image URLs are stable for the lifetime of the entity.
- Error `message` text is always safe to display directly.

## 7. Acceptance criteria

- Every endpoint in the table has exactly one owner spec and appears in that spec's acceptance criteria.
- All request validation failures return the standard error format with `VALIDATION_ERROR` and per-field details.
- No response ever contains a filesystem path, an API key or a stack trace.
- An AI failure always yields a standard error response and never leaves a generation in `running`.
