# 06 - Project and Upload

**Purpose:** project lifecycle (create, list, open, rename, delete) and exterior image upload, validation, storage and retrieval, including the Project List and Upload screens.
**Depends on:** `01-data-model.md`, `02-api-contracts.md`, `03-frontend-foundation.md`, `04-backend-foundation.md`.
**Endpoints owned (from `02`):** #3-#11 (projects and photos). Request/response shapes are defined in `02` and are not repeated here except where behaviour needs clarifying.
**Note:** project CRUD is already implemented and verified. Sections 2 and 3 are the reference for that behaviour and the baseline for its tests; section 4 onward is new work.

---

## 1. Scope

In scope: project CRUD rules; upload of one exterior image per project (schema allows up to `MAX_PHOTOS_PER_PROJECT`), including real photographs and 3D architectural renderings; technical validation; storage; image retrieval; image deletion; Project List screen; Upload screen.
Out of scope: AI quality assessment of the photo (`07`), multi-photo fusion, image editing or cropping, accounts.

## 2. Project rules

| Operation | Rules |
|-----------|-------|
| Create (`POST /api/projects`) | `name`: trimmed, 1-100 characters, no control characters. In one transaction: insert project (`last_step = "upload"`), insert variant `Design 1`, set `active_variant_id`. Create `projects/{project_id}/` directory after commit. Returns `201` Project. |
| List (`GET /api/projects`) | `limit` 1-100 (default 50), `offset` >= 0. Ordered by `updated_at` descending, `id` as tiebreaker. Includes derived `photo_count`, `component_count`, `variant_count`. Response `{ "items": [...], "total": n }`. |
| Get | Returns Project with derived counts. Malformed or unknown ID: `404 NOT_FOUND` (`details.resource = "project"`). |
| Patch (`PATCH`) | At least one of `name`, `last_step`, `active_variant_id`, `floor_count`. `last_step` must be a `project_step` value. `floor_count`: integer 1-6 or null. `active_variant_id` must belong to the project, else `404`. A `last_step`-only patch must **not** change `updated_at` (it is a navigation hint, not a data change). Any other field updates `updated_at`. |
| Delete | Delete database rows (cascade), then remove `projects/{project_id}/`. If directory removal fails, log a warning and still return `204`. |

## 3. Project List screen (`projects.js`)

| Element | Behaviour |
|---------|-----------|
| Header action | Primary button "New project" opens a modal with a name field (default "My house"). Submit creates the project and navigates to `#/p/{id}/upload`. |
| Project cards | Name, "Updated {date}", counts ("1 photo, 12 regions, 2 designs"), and the step to resume ("Continue: Components"). The card opens `#/p/{id}` (redirects to `last_step`, per `03`). |
| Card actions | Rename (inline edit; `PATCH name`), Delete (confirm: "This permanently deletes the project, its photo, designs and reports."). |
| Empty state | "No projects yet. Create one to start." with the New project button. |
| Paging | "Load more" button when `total` exceeds the items shown. |
| Errors | Handled by the shared handlers (`03` section 8.2). A failed list shows a retry button. |

No thumbnails are shown (the Project shape has no photo reference).

## 4. Photo upload pipeline

**Endpoint:** `POST /api/projects/{project_id}/photos`, `multipart/form-data`, one field `file`.

### 4.1 Server steps (in order; the first failure stops the request)

| # | Step | Failure |
|---|------|---------|
| 1 | Project exists | `404 NOT_FOUND` |
| 2 | `file` field present and non-empty | `422 VALIDATION_ERROR` (`fields: [{field: "file", problem: "a photo is required"}]`) |
| 3 | An optional preliminary photo-count check may reject a project already at its limit, but it does not reserve a slot and is never authoritative | `409 PHOTO_LIMIT_REACHED` |
| 4 | If a `Content-Length` header is present and exceeds the limit by a clear margin, reject early. Then read the body in chunks, stopping as soon as total bytes exceed `MAX_UPLOAD_MB` | `413 UPLOAD_TOO_LARGE` |
| 5 | Decode the bytes as an image (verification pass, then a fresh decode). The detected **format** decides the type, not the file extension or declared MIME | undecodable: `422 UPLOAD_CORRUPT` |
| 6 | Format must map to an allowed MIME (`JPEG`, `PNG`, `WEBP`). Multi-frame or animated images are rejected | `415 UPLOAD_INVALID_TYPE` |
| 7 | Read pixel dimensions **before** decoding fully; reject images above `MAX_IMAGE_PIXELS` (defined in `04` section 4) to prevent decompression abuse | `413 UPLOAD_TOO_LARGE` (message names the dimension limit) |
| 8 | Apply EXIF orientation to obtain the upright width and height | |
| 9 | `min(width, height)` >= `MIN_IMAGE_SHORT_SIDE_PX` | `422 UPLOAD_TOO_SMALL` |
| 10 | Generate `photo_id` and save the original bytes unchanged to `projects/{project_id}/original/{photo_id}.{ext}` (`ext`: `jpg`, `png`, `webp` from the detected format) via the storage helper | storage failure: `500 INTERNAL_ERROR` |
| 11 | In a write-serialized SQLite transaction (`BEGIN IMMEDIATE`), re-check that the project still exists and that its photo count is below `MAX_PHOTOS_PER_PROJECT`; choose the smallest unused `view_index` in `1..MAX_PHOTOS_PER_PROJECT`; insert the `photos` row (upright width/height; `quality_usable`, `quality_reason`, `detected_at` null) and touch the project. The count check, index allocation and insert are atomic. On any failure, roll back and delete the saved file. | project deleted: `404 NOT_FOUND`; limit reached: `409 PHOTO_LIMIT_REACHED`; other insert failure: `500 INTERNAL_ERROR` |
| 12 | Return `201` Photo | |

Notes:
- The stored file is the original bytes. Orientation is applied whenever pixels are consumed by the backend (`05` working image, `12` report). Browsers apply EXIF orientation when showing the image, so the browser display matches the stored upright width and height.
- The authoritative count check and row insertion use the same `BEGIN IMMEDIATE` transaction. SQLite serializes competing writers, so concurrent uploads cannot both consume the final available slot. Image validation and file writing happen before this transaction; a saved file is removed if the transactional re-check or insert fails.
- `original_filename` is the client name reduced to its base name, with control characters and path separators removed, truncated to 120 characters, defaulting to `photo`. It is for display only (`01`).
- The upload step performs **technical** checks only (decodable, allowed format, size, resolution), regardless of whether the image is a photograph or a rendering. Whether the image shows a usable residential exterior is judged by detection (`07`).
- No upload endpoint ever calls an AI model.

### 4.2 Error messages (user-safe)

| Code | Message |
|------|---------|
| `UPLOAD_INVALID_TYPE` | This file type is not supported. Please upload a JPG, PNG or WebP photo. |
| `UPLOAD_TOO_LARGE` | This photo is too large. Please upload a file under {MAX_UPLOAD_MB} MB. (For the pixel limit: "This photo's dimensions are too large. Please resize it and try again.") |
| `UPLOAD_TOO_SMALL` | This photo is too small ({w} x {h}). Please upload one at least {MIN} pixels on its shorter side. |
| `UPLOAD_CORRUPT` | We could not read this image. Please try a different photo. |
| `PHOTO_LIMIT_REACHED` | This project already has a photo. Delete it first to upload a different one. |

### 4.3 Retrieval and deletion

| Endpoint | Behaviour |
|----------|-----------|
| `GET .../photos` | `{ "items": [Photo] }` ordered by `view_index`. Each Photo includes `image_url`. |
| `GET .../photos/{photo_id}/image` | Streams stored bytes with the stored MIME type and headers from `04` section 6. Photo not in this project: `404`. Missing file: `404` plus a warning log. |
| `DELETE .../photos/{photo_id}` | Deletes the row (cascading detected components, components, selections, measurements, generations per `01` section 7.2), then deletes the photo file and the generated-image files of the removed generations. Touches the project. Reports are kept. Returns `204`. |

## 5. Upload screen (`upload.js`)

### 5.1 States

| State | Display |
|-------|---------|
| No image | Drop zone ("Drag an image here or choose a file"), tips panel, privacy note, accepted types and size from `GET /api/client-config` |
| Uploading | Progress bar with percentage (uses an upload request that reports progress, per `03` section 7), drop zone disabled |
| Photo present | Large photo preview, file name, dimensions, **Replace photo** (secondary), primary button **Continue to Components** |
| Error | Inline error under the drop zone with the server message and a "Choose another photo" button |

### 5.2 Image guidance (always shown beside the drop zone)

- Display: "Upload a clear exterior photograph or 3D architectural rendering of your house."
- For photographs, prefer daylight, a front view, and enough distance to show the whole house; keep the camera level and avoid strong angles.
- For photographs or renderings, avoid images where large obstructions hide the building or the facade is cropped.
- Upload one side of the house per image.

### 5.3 Privacy note

"Your image is sent to Google's Gemini service to analyse it and to create the redesign. Do not upload images you are not comfortable sharing."

### 5.4 Client-side pre-checks (convenience only)

Before uploading, the browser checks: file type is in `allowed_mime_types`, size <= `max_upload_mb`, and (by decoding the image locally) the short side >= `min_short_side_px`. A failed pre-check shows the same message text as section 4.2 without any request. The server remains the authority; its errors are always handled.

### 5.5 Behaviours

- Upload is by drag-and-drop or file chooser, one file only. Dropping several files uses the first and shows "Only one photo is used per project."
- **Replace photo** = confirm ("Replacing the photo removes its detected regions, material choices and designs"), `DELETE` the old photo, then show the drop zone. Upload is a new request.
- After a successful upload, store is refreshed, the project's `last_step` becomes `components`, and **Continue to Components** is shown. The app does not navigate automatically and does not trigger detection (detection is an explicit user action in `07`).
- HEIC and other unsupported formats show the invalid-type message with the extra hint "iPhone users: choose 'Most Compatible' camera format or export as JPG."

## 6. Validation summary

| Input | Rule |
|-------|------|
| Project name | 1-100 characters after trim |
| Photo file | Allowed formats JPEG/PNG/WebP, single frame, <= `MAX_UPLOAD_MB`, <= `MAX_IMAGE_PIXELS` from `04`, short side >= `MIN_IMAGE_SHORT_SIDE_PX` |
| `floor_count` | Integer 1-6 or null |
| IDs in paths | Prefixed 16-hex format (`04` section 7) |

## 7. Edge cases

| Case | Behaviour |
|------|-----------|
| Two simultaneous uploads to the same project | After validation and storage, each upload re-checks count and inserts under `BEGIN IMMEDIATE`; one succeeds, the other gets `PHOTO_LIMIT_REACHED`. A saved file for the loser is deleted. |
| Client disconnects mid-upload | No partial file or row remains |
| Photo with unusual aspect (panorama, very tall) | Accepted; the UI scales it; quality judgement is left to `07` |
| Photo with rotation metadata | Upright dimensions stored; browser and backend consumers show it upright |
| Re-upload after delete | New `photo_id`; no reuse of old data |
| Project deleted while its photo is open in another tab | Subsequent requests return `404`; the UI shows "project not found" (`03` section 3) |

## 8. Acceptance criteria

- Creating a project with a blank or 101-character name returns `422 VALIDATION_ERROR` with field details.
- `PATCH` with only `last_step` leaves `updated_at` unchanged.
- Uploading a valid JPEG, PNG and WebP each returns `201`; the file exists under `projects/{id}/original/`, and the width/height are upright dimensions.
- A clear exterior photograph and a clear 3D architectural rendering both pass the same technical upload checks; rendered images are not rejected because they are computer-generated. Semantic suitability is assessed by `07`.
- A text file renamed to `.jpg` returns `422 UPLOAD_CORRUPT`; a GIF returns `415 UPLOAD_INVALID_TYPE`; an 11 MB file (limit 10) returns `413 UPLOAD_TOO_LARGE`; a 400 x 300 image returns `422 UPLOAD_TOO_SMALL`.
- A second upload to a one-photo project returns `409 PHOTO_LIMIT_REACHED`.
- A portrait phone photo with EXIF rotation reports the upright width and height, and displays upright in the UI.
- Deleting the photo removes its components, selections, measurements and generations and files; the project and any reports remain.
- Deleting a project removes all its rows and its directory.
- The client's file name never appears in a stored path.
- No upload or project endpoint contacts an AI provider.
