# 07 - Component Detection

**Purpose:** detecting exterior components in an uploaded residential exterior photograph or rendering with Gemini Vision, validating and saving the result, assessing image usability, and the detection-related states of the Components screen.
**Depends on:** `01-data-model.md`, `02-api-contracts.md`, `05-ai-integration.md`, `06-project-and-upload.md`.
**Endpoint owned (from `02`):** #12 `POST /api/projects/{project_id}/photos/{photo_id}/detect`.
**Hands off to:** `08` (editing the detected components).

---

## 1. Scope

In scope: the detection prompt and output schema, conversion and validation of boxes, saving normalized valid detections and working components, preservation of user corrections, image quality flag, detection stage run, the pre-editor states of the Components screen.
Out of scope: segmentation masks, depth, perspective, measurements (`11`), editing UI (`08`), the catalogue (`09`).

**Design position.** Detection produces *approximate rectangular regions*, not exact outlines. A box is a hint for the user and the redesign prompt, not a pixel mask. The user's review (`08`) is the correction mechanism.

## 2. Rules

1. AI detections never overwrite or remove a locked component (`01` section 4.5).
2. The detector reports everything visible, including things the catalogue does not support. Support is derived later from the catalogue (`01` section 5); the detector is not told what is customizable.
3. `detected_components` stores normalized, valid detection records, not the raw model response. The full model response is not persisted; only the bounded diagnostic excerpt allowed by `05` may appear in stage-run detail.
4. A failed or unusable detection leaves components and selections unchanged.
5. Detection only runs when the user asks for it.

## 3. Component vocabulary (from `01` section 3.1)

`wall`, `window`, `door`, `balcony`, `railing`, `pillar`, `parapet`, `gate`, `roof_edge`, `other`.

Definitions given to the model (section 6):

| Type | Definition |
|------|-----------|
| `wall` | A continuous exterior wall surface of the main building. One entry per visible wall section (e.g. per facade segment or per floor where clearly separate). The box may enclose windows or doors within it. |
| `window` | Each individual window |
| `door` | Each individual entrance or balcony door |
| `balcony` | The balcony structure itself (slab edge, front face), not its railing |
| `railing` | Each railing, balustrade or grille (balcony, terrace or staircase) |
| `pillar` | Each pillar or column |
| `parapet` | Each parapet wall (low wall at roof or terrace edge) |
| `gate` | Each gate or gate area at the compound entrance |
| `roof_edge` | The roof edge, eave, fascia or visible roof-line trim |
| `other` | Anything else notable that is not part of the building envelope (pavement, vehicles, trees, signage). At most 5. Sky and background are not reported. |

## 4. Endpoint behaviour

`POST /api/projects/{project_id}/photos/{photo_id}/detect`, no body, synchronous. Response shape is exactly as in `02` section 5.4.

### 4.1 Flow

| # | Step | Failure |
|---|------|---------|
| 1 | Project and photo exist and the photo belongs to the project | `404 NOT_FOUND` |
| 2 | No detection stage run for this project is already `running` (checked and the new run inserted in one transaction) | `409 CONFLICT`, `details.reason = "detection_in_progress"` |
| 3 | Insert stage run (`stage = "detection"`, `status = "running"`) and commit | |
| 4 | Build the working image (`05` section 4) | Any exception after step 3: attempt to mark the run `failed`; surface `500 INTERNAL_ERROR` |
| 5 | Call the Vision interface (`05` section 5.1) with the detection prompt (section 6) and the strict envelope schema (section 5). **No database transaction is open.** | Any `AI_*` error: attempt to mark the run `failed`, re-raise; photo and components untouched |
| 6 | Validate individual entries and normalize the result (section 7). Invalid entries are dropped without retrying a valid envelope. | Any exception after step 3: attempt to mark the run `failed`; surface the applicable error |
| 7 | **If `usable` is false:** in one transaction update the photo (`quality_usable = 0`, `quality_reason`, `detected_at = now`) and mark the stage run `succeeded` with `usable: false` in its detail. Return the response with the existing working set unchanged. Stop. | Any exception after step 3: attempt to mark the run `failed`; surface the applicable error |
| 8 | Otherwise, in **one transaction**: persist as described in section 8 and mark the stage run `succeeded` with duration and detail | Any exception after step 3: attempt to mark the run `failed`; surface the applicable error |
| 9 | Return the response | |

The service wraps all work after stage-run creation so **every exception** attempts to update that run to `failed`, with `finished_at`, duration, error code and a safe message, then re-raises the original error. If recording the failure also fails, log that failure explicitly and do not replace or suppress the original exception. A process termination cannot be handled in-request; interrupted-run recovery is specified in `04`.

An unsuitable image is a **successful** operation (`200`) with `usable: false`.

## 5. Strict top-level response schema

The Vision model is asked to return exactly this JSON object (field names are final):

```json
{
  "usable": true,
  "quality_reason": null,
  "components": [
    {
      "type": "wall",
      "label": "main front wall, ground floor",
      "box_2d": [ymin, xmin, ymax, xmax],
      "confidence": 0.9
    }
  ]
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `usable` | boolean | `false` only when the image clearly cannot support renovation planning |
| `quality_reason` | string or null | If `usable` is false: plain-language guidance telling the user what suitable image to provide (max 200 chars). If true: optional advisory (e.g. "The right side of the house is cut off."), else null. |
| `components` | array of unvalidated values | Required array. Entries are validated independently in section 7. |
| `components[].type` | string | One of the vocabulary values |
| `components[].label` | string | Short location description, 3-10 words, e.g. "first-floor balcony railing, left" |
| `components[].box_2d` | 4 finite numbers | `[ymin, xmin, ymax, xmax]` on a **0-1000 scale** relative to the image, origin top-left |
| `components[].confidence` | number 0-1 | The model's confidence; optional or invalid values normalize to null |

The top-level object must contain exactly `usable`, `quality_reason`, and `components`. `usable` must be a boolean, `quality_reason` must be a string or null, and `components` must be an array. A missing, extra, or wrongly typed top-level field makes the envelope invalid and is eligible for the Vision retry in `05`. Component entries are deliberately not validated as part of this envelope: each entry is processed independently in section 7, and an invalid entry is dropped without retrying the otherwise valid response.

**M0 verification (`05` section 12):** the `box_2d` convention is the one believed to be used by the Vision model family. It must be confirmed by drawing the boxes on test photos. The conversion in section 7.2 is the only place that depends on it.

### Image is unusable when (guidance given to the model)

Too blurry to identify surfaces; extremely dark or overexposed; does not show a recognizable residential exterior; is an interior; the building is mostly hidden or cropped; or is a floor plan or unrelated drawing that cannot support exterior component identification. When uncertain, the model should prefer `usable: true` with an advisory in `quality_reason`.

Clear real residential exterior photographs, 3D architectural renderings, CGI exterior visualizations, and other computer-generated residential building images are all acceptable. The model must identify visible exterior components in photographs and renderings and must not mark an image unusable solely because it is digitally rendered or computer-generated.

## 6. Detection prompt (version `det-v2`)

Assembled in code from this fixed template. There is no user text in this prompt.

```
You are analysing an exterior image of a residential building to help plan a
renovation. Accept real residential exterior photographs, 3D architectural renderings,
CGI exterior visualizations, and other computer-generated images of residential buildings.
Identify visible exterior components in both photographs and rendered images. Do not mark an image unusable merely because it is digitally rendered or computer-generated.

TASK
1. Decide whether the image is usable for exterior renovation planning.
2. List the visible exterior components of the main building with approximate
   bounding boxes.

OUTPUT
Reply with ONLY one JSON object, no other text, in exactly this shape:
{"usable": boolean, "quality_reason": string or null,
 "components": [{"type": string, "label": string,
                 "box_2d": [ymin, xmin, ymax, xmax], "confidence": number}]}

RULES FOR box_2d
- Four integers on a 0-1000 scale, relative to the full image.
- Order is [ymin, xmin, ymax, xmax]. Origin is the top-left corner.
- The box must tightly enclose the component.

COMPONENT TYPES (use only these values for "type")
wall, window, door, balcony, railing, pillar, parapet, gate, roof_edge, other
- wall: one entry per visible wall section of the main building. A wall box may
  contain windows and doors inside it.
- window, door, railing, pillar, parapet, gate: one entry per individual item.
- balcony: the balcony structure itself, not its railing.
- roof_edge: roof edge, eave or fascia trim.
- other: notable items that are not part of the building (pavement, vehicles,
  trees, signs). Report at most 5. Do not report sky or distant background.

LABELS
- 3 to 10 words describing which one it is, including floor and side where
  possible, for example "first-floor balcony railing, left".
- Labels must be unique within the reply.

LIMITS
- Report at most 40 components. Prefer larger and more important components.
- Do not invent components that are not visible.
- confidence is a number from 0 to 1.

USABILITY
- Set usable to false if it is too blurry to identify surfaces, extremely dark
  or overexposed, does not show a recognizable residential exterior, is an
  interior, shows a building that is mostly hidden or cropped, or is a floor plan
  or unrelated drawing that cannot support exterior component identification.
- A clear exterior rendering or computer-generated image is usable just like a
  photograph. Do not reject it because it is not a real photograph.
- If usable is false, set quality_reason to one or two short sentences telling
  the owner what kind of clearer exterior image to upload, and return an empty
  components list.
- If usable is true, quality_reason may contain one short advisory sentence
  (for example about a cut-off side) or null.
```

Retry suffix on invalid output is defined in `05` section 5.1.

## 7. Validation and normalization (service, after schema validation)

Applied in this order. Invalid items are **dropped** and counted; the response carries a warning per category of dropped items, not one per item.

### 7.1 Top-level

| Check | Handling |
|-------|----------|
| Top-level object, required keys, or field types invalid | Envelope schema failure (retried by `05`) |
| `quality_reason` | Trim; truncate to 200 characters; empty string becomes null |
| `usable: false` with a null or empty reason | Use the default: "This image can't be used. Please upload a clear exterior photograph or 3D architectural rendering of the whole house." |
| `usable: true` | Process components |
| `usable: false` | Ignore any components returned |

### 7.2 Per component

| Check | Handling |
|-------|----------|
| Entry is not an object, or `type` is not a string, or `box_2d` is not a list of exactly four finite numbers | Drop and increment `dropped_invalid` |
| `type` not in vocabulary (after lowercase and trim; spaces/hyphens to underscore) | Map to `other`, increment `remapped_types` |
| Values outside 0-1000 | Clamp to 0-1000 |
| `ymin > ymax` or `xmin > xmax` | Swap |
| Conversion to normalized box | `x = xmin / 1000`, `y = ymin / 1000`, `w = (xmax - xmin) / 1000`, `h = (ymax - ymin) / 1000`, rounded to 4 decimals |
| `w < 0.02` or `h < 0.02` | Drop as too small (`dropped_small`) |
| Box satisfies `01` box constraint | Guaranteed by clamping; verify, otherwise drop |
| `label` | If a string, trim, collapse whitespace, strip control characters and truncate to 120; if missing, non-string or empty, use the type's display label |
| `confidence` | Number clamped to 0-1; if missing, non-finite or not numeric, use null |

### 7.3 Set level

| Check | Handling |
|-------|----------|
| Near-duplicates: same `type` and intersection-over-union >= 0.85 | Keep the one with higher confidence (`dropped_duplicate`) |
| More than 40 components | Keep the 40 with highest confidence, but never drop a `wall` before other types (`dropped_over_limit`) |
| More than 5 `other` | Keep the 5 largest by area |
| Duplicate labels | Append " 2", " 3", ... to later ones |
| Zero normalized valid components with `usable: true` | Allowed; add warning "No components were found. You can add regions manually." |

## 8. Persistence (single transaction)

Let `P` be the photo. In order:

1. **Insert normalized detection records.** One `detected_components` row per valid component retained after individual and set-level normalization in section 7 (`stage_run_id` = this run). These rows are never modified later. They are not raw model output; rejected entries and the original full JSON response are not persisted.
2. **Delete replaceable components.** Delete `components` where `photo_id = P` and `origin = 'ai'` and `is_locked = 0`. Their selections and measurements are removed by cascade (`01`). Count `removed_selections` and `removed_measurements` before deleting, for the warning in step 6.
3. **Count locked components** on `P` (all origins) as `kept_locked_count`.
4. **Insert new working components.** For each valid detected component:
   - If a **locked** component on `P` has the same `type` and IoU >= 0.5 with it, skip (the user's version stands; count `skipped_overlap`).
   - Otherwise insert into `components` with `origin = 'ai'`, `is_locked = 0`, `source_detection_id` set, `confidence` from detection.
   - Respect `MAX_COMPONENTS_PER_PHOTO` (defined once in `04` section 4): stop inserting when the total reaches it (`dropped_over_limit`).
5. **Update the photo:** `quality_usable = 1`, `quality_reason` (advisory or null), `detected_at = now`.
6. **Build warnings** (strings, only when the associated count is above zero, except the explicit zero-components condition):
   - "{n} detected regions were hidden because they overlap regions you edited." (`skipped_overlap`)
   - "{n} very small regions were ignored." (`dropped_small`)
   - "{n} duplicate regions were merged." (`dropped_duplicate`)
   - "{n} invalid region entries were ignored." (`dropped_invalid`)
   - "{n} regions with unrecognised types were marked as Other." (`remapped_types`)
   - "Replacing the previous results removed {s} material choice(s) and {m} measurement(s) linked to those regions." (when either is > 0)
   - "Only the first {n} regions were kept." (`dropped_over_limit`)
   - "No components were found. You can add regions manually." when there are no normalized valid detection records.
7. Touch the project (`updated_at`).

Order of `components` in the response: `created_at` ascending, `id` ascending. The frontend draws larger boxes first so small ones remain clickable (`03` section 9, `08`).

**Known limitation (documented in `13`):** re-running detection replaces unedited AI regions, which removes material choices and measurements attached to them, and a region the user deleted may reappear. The UI confirmation (section 10.3) warns about this. Matching old to new regions to preserve choices is postponed.

## 9. Response

Exactly the shape in `02` section 5.4:

| Field | Value |
|-------|-------|
| `stage_run_id` | The run created in step 3 |
| `photo` | The updated Photo |
| `usable` | boolean |
| `quality_reason` | string or null |
| `components` | Full current working set of the photo (each with `supported`, `is_locked`, etc., per `02` section 3.3) |
| `kept_locked_count` | integer |
| `warnings` | array of strings |

For an unusable result, `components` is the unchanged working set and `warnings` is empty.

### Stage run detail (`stage_runs.detail_json`)

```
{
  "model": "...", "prompt_version": "det-v2", "attempts": 1,
  "image_sent": { "width_px": ..., "height_px": ..., "bytes": ... },
  "usable": true,
  "raw_count": 14, "inserted": 12, "kept_locked": 2,
  "dropped_small": 1, "dropped_duplicate": 1, "dropped_invalid": 0, "remapped_types": 0,
  "skipped_overlap": 0, "dropped_over_limit": 0,
  "response_excerpt": "..."
}
```

## 10. Components screen: detection states (frontend)

The Components screen (`components.js`) is shared with `08`. This section covers the states before and around the editor.

### 10.1 States

| State | Condition | Display |
|-------|-----------|---------|
| No image | Project has no image | Prerequisite panel: "Upload a clear exterior photograph or 3D architectural rendering of your house." with a button to Upload (`03` section 5) |
| Not detected | Image exists, `detected_at` null, no components | Image preview, short explanation ("We will look for walls, windows, balconies, pillars and other parts of your house. You can correct anything afterwards."), primary button **Detect components**, secondary link **Skip and draw regions myself** (opens the editor of `08` with an empty set) |
| Detecting | Request in flight | Busy overlay (`03` section 8.1): "Analysing your house exterior image..." |
| Unusable | Last response `usable: false` | Amber guidance panel with `quality_reason`, buttons **Replace image** (to Upload) and **Draw regions anyway** (opens the editor) |
| Detected, no regions found | Last response is successful and usable, and the full current working set is empty | Say detection completed but found no regions; show **Detect again** and **Draw regions myself** to open the editor with an empty set |
| Ready | Components exist | Editor (`08`), with an advisory banner if `quality_reason` is set |
| Detection failed | Any `AI_*` error | Error toast and an inline panel: the server message, **Try again**, and **Draw regions myself** (so the flow is never blocked by an AI outage) |

### 10.2 After a successful detection

- Store is updated from the response (`photo`, `components`).
- Summary line above the editor: "Found {n} regions ({k} you can customise)". `k` counts `supported: true`.
- Warnings are shown in a dismissible amber list.
- If `usable` is true and `quality_reason` is set, show it as an info banner.
- When a successful usable detection returns no working components, show the dedicated **Detected, no regions found** state instead of the editor-ready state. The user can retry or draw components manually; this is a successful detection, not a detection failure.

### 10.3 Re-detection

A secondary button **Detect again** in the editor toolbar. Confirmation text:
"Detecting again replaces the regions that you have not edited. Regions you added or changed are kept. Material choices and measurements linked to replaced regions will be removed. Continue?"

### 10.4 Persistence of the "skipped" path

Skipping detection does not set `detected_at`. A user who draws manually can proceed to the Materials step. The Components stepper state is complete only after a successful usable detection (`quality_usable = 1` and `detected_at` set), including when it found zero regions; a manual-only project remains available rather than done. This does not block progress.

## 11. Error handling summary

| Situation | Result |
|-----------|--------|
| Image or project not found | `404 NOT_FOUND` |
| Detection already running for the project | `409 CONFLICT` (`detection_in_progress`) |
| Key or models not configured | `503 AI_NOT_CONFIGURED` |
| Timeout, rate limit, provider error, content block, invalid output | `AI_*` per `05` section 7; stage run `failed`; components and photo unchanged |
| Image judged unusable | `200` with `usable: false` |
| Zero components found | `200` with a warning |
| Database error while saving | Transaction rolled back, stage run `failed`, `500 INTERNAL_ERROR`; previous components intact |

Stage runs left `running` after a crash are handled at startup (`04` section 3).

## 12. Acceptance criteria

- With mock mode (`ok`), detecting a photo returns about 10 components, all with valid normalized boxes, and they appear on the photo.
- With a clear residential exterior rendering, the detector returns `usable: true` and identifies visible components; it does not reject the image solely because it is computer-generated.
- Clear exterior photographs and renderings proceed through the same component editing, material selection and measurement workflow.
- Interior images, floor plans/unrelated drawings that do not show identifiable exterior components, and genuinely blurry, extremely dark, mostly hidden or cropped images remain unusable.
- Each normalized valid component is stored in `detected_components`; inserted working components have `origin = "ai"`, `is_locked = false`.
- A usable detection with an empty components array returns `200`, stores the usable quality flag, emits the no-components warning, and shows **Detected, no regions found** with retry and manual-draw actions.
- An invalid top-level envelope is retried; invalid individual entries in a valid envelope are dropped and counted without retrying.
- After the user edits one component and detection runs again, that component is unchanged and still locked; unedited AI components are replaced; `kept_locked_count` reflects the locked ones.
- A newly detected component overlapping a locked one of the same type (IoU >= 0.5) is not inserted.
- `usable: false` returns `200`, updates `quality_usable` and `quality_reason`, leaves `components` unchanged, and shows the guidance panel.
- Each failing mock scenario (`invalid_json`, `blocked`, `timeout`, `rate_limited`) returns the mapped error code, leaves the existing components untouched and marks the stage run `failed`.
- Types outside the vocabulary become `other`; boxes outside the image are clamped; reversed boxes are swapped; boxes under 2% in either dimension are dropped.
- A second detection request while one is running returns `409 CONFLICT`.
- Detecting a photo whose project has selections on unedited AI regions removes those selections and the response warns about it.
- The AI never creates, edits or deletes a locked component.
- The detection prompt contains no user-provided text.
- Real-model check (M0): on test photographs and at least one clear 3D architectural exterior rendering, boxes land on intended objects; unsuitable-image classes remain rejected.
