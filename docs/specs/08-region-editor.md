# 08 - Region Editor

**Purpose:** reviewing and correcting detected components: the component management endpoints, their business rules, and the editor UI on the Components screen (select, retype, relabel, redraw, add, delete).
**Depends on:** `01-data-model.md`, `02-api-contracts.md`, `03-frontend-foundation.md`, `07-component-detection.md`, and the read-only catalogue compatibility foundation in `09` (implemented before this spec; see `00` section 4).
**Endpoints owned (from `02`):** #13 list, #14 add, #15 edit, #16 delete components.
**Shares the Components screen with `07`**, which owns the states before the editor appears.
**Enables:** `09` (selections attach to components), `10` (redesign uses confirmed regions), `11` (measurements attach to components).

---

## 1. Scope

In scope: component CRUD behaviour, locking, cascade effects, the editor UI, validation, error handling. The backend uses the in-process catalogue compatibility lookup from `09`; component editing does not call selection or measurement HTTP endpoints.
Out of scope: detection (`07`), catalogue definition and selection endpoints (`09`), resize handles, undo/redo, move-by-drag, polygon outlines, "reset to AI result".

**Principle.** Every edit is saved immediately through the API. There is no separate "save" step. "Confirmed components" simply means the current working set when the user moves on to the Materials step.

## 2. Constants

| Rule | Value | Owner |
|------|-------|-------|
| Maximum components per photo | `MAX_COMPONENTS_PER_PHOTO` | Shared backend configuration in `04` section 4; do not redefine here |
| Label length | 1-120 characters | Trimmed; control characters removed |
| Minimum box size | 0.02 normalized in both dimensions | Server-side validation floor |
| Minimum drawn drag | 1.5% of image width/height | Client-side, from `03` section 9 |

The catalogue compatibility foundation is a read-only in-process service/data lookup, not an HTTP endpoint. `08` uses it only for deriving `supported` and applying component-type-change effects. It does not depend on the future variant, selection, or measurement endpoints.

## 3. Endpoint behaviour

Shapes are in `02` section 5.5. Rules below add behaviour.

### 3.1 List: `GET /api/projects/{project_id}/components?photo_id=`

- `photo_id` optional. If given and not in the project: `404 NOT_FOUND` (`details.resource = "photo"`).
- Order: `created_at` ascending, `id` ascending.
- Each item includes backend-derived `supported` (`01` section 5): true when the loaded catalogue compatibility lookup has at least one material compatible with the component's `type`. The frontend treats this returned value as authoritative.

### 3.2 Add: `POST /api/projects/{project_id}/components`

Request: `{ "photo_id", "type", "label"?, "box": {x,y,w,h} }`.

| Rule | Detail |
|------|--------|
| Photo | Must belong to the project, else `404 NOT_FOUND` |
| `type` | In the vocabulary, else `422 VALIDATION_ERROR` |
| `label` | Optional; if absent or blank, use the type's display label from the vocabulary (e.g. "Wall") |
| `box` | Numbers; `x, y >= 0`; `w, h >= 0.02`; `x + w <= 1` and `y + h <= 1` within a 0.001 tolerance, then clamped to the image; otherwise `422` |
| Limit | If the photo already has `MAX_COMPONENTS_PER_PHOTO` components: `409 CONFLICT`, `details.reason = "component_limit"`, message "This photo already has the maximum number of regions." |
| Stored as | `origin = "user"`, `is_locked = 1`, `confidence = null`, `source_detection_id = null` |
| Response | `201` Component |
| Side effects | Touch the project. No effect on selections or generations until the component receives a selection. |

### 3.3 Edit: `PATCH /api/projects/{project_id}/components/{component_id}`

Request: any of `type`, `label`, `box`. At least one is required, else `422`. Validation as in 3.2.

Processing (one transaction):

1. Load the component (must belong to the project, else `404`).
2. Determine which fields **actually change** (compare normalized values; box values are compared rounded to 4 decimals). If nothing changes, return `200` unchanged with all counters zero and do **not** lock it.
3. Apply changes; set `is_locked = 1`; update `updated_at`. `origin` and `source_detection_id` are unchanged (an edited AI component keeps its provenance but is locked).
4. **If `type` changed:** the component service uses the in-process catalogue compatibility lookup from `09` to check selections attached to this component in the database across the project's variants. Delete incompatible selections and count them as `removed_selections`. If the new type is unsupported, all of its selections are removed. This is a backend service/repository operation within the component edit transaction, not an HTTP call to another endpoint.
5. **If `box` or `type` changed:** delete the component's measurement if its `source` is `ai_estimate` (set `removed_ai_measurement = true`). A `user` measurement is kept. A label-only change does not affect measurements. *(This follows `01` section 4.9; the effects table in `01` section 7.2 is broader in wording but the measurement rule in 4.9 governs.)*
6. Touch the project.
7. Build `warnings` (strings):
   - "{n} material choice(s) were removed because the new type does not support them." when `removed_selections > 0`
   - "The AI-estimated measurement for this region was removed because the region changed." when `removed_ai_measurement`
   - "Your measurement for this region was kept. Please check it still applies." when the box or type changed and a `user` measurement exists

Response `200`:

```json
{
  "component": { "...Component..." },
  "removed_selections": 1,
  "removed_ai_measurement": false,
  "warnings": []
}
```

Generations that used this component become stale automatically through their fingerprint (`01` section 7); no write to generations is needed.

### 3.4 Delete: `DELETE /api/projects/{project_id}/components/{component_id}`

- Not found or wrong project: `404`.
- Deletes the component. Selections and the measurement are removed by cascade. Touch the project. Returns `204`.
- Deleting does not remove the raw `detected_components` row.
- Locked and unlocked components can both be deleted.

## 4. Behavioural rules

1. **Locking.** User-created and user-edited components are locked. There is no unlock operation; a locked component stays locked until it is deleted. Locked components survive re-detection (`07` section 8).
2. **Types.** The editor can set any vocabulary type. Changing a wall to a window or `other` is allowed (the component becomes non-customizable).
3. **Overlap.** Components may overlap freely (a wall contains windows). The server does not check overlaps.
4. **Support is derived.** `supported` is recomputed on every read; it is never stored (`01`).
5. **Unsupported components** remain visible, can be edited and deleted, but cannot receive materials (`09` enforces compatibility on selection writes) and are excluded from the redesign edit instructions (`10`).
6. **No hidden changes.** The AI and the server never edit a component on their own after creation, apart from the detection replacement of unlocked AI components defined in `07`.

## 5. Components screen: editor UI (`components.js`, using `imagestage.js`)

Shown when components exist or when the user chose to draw manually (`07` section 10).

### 5.1 Layout

```
+---------------------------------------+---------------------------+
| Toolbar: [Select] [Add region]        |  Regions (12)             |
|          [Detect again]  [Show: all v]|  [Customisable | All]     |
+---------------------------------------+---------------------------+
|                                       |  list of components       |
|   photo with box overlay              |  (type, label, badges)    |
|                                       +---------------------------+
|                                       |  Details of selected      |
|                                       |  type [dropdown]          |
|                                       |  label [text]             |
|                                       |  [Redraw box] [Delete]    |
+---------------------------------------+---------------------------+
| [Back: Upload]                      [Next: Choose materials]      |
+--------------------------------------------------------------------+
```

On narrow screens the side panel stacks below the photo.

### 5.2 Display

| Element | Behaviour |
|---------|-----------|
| Boxes | Percentage-positioned overlay per `03` section 9; colour by type; label chip "Type: label" truncated |
| Drawing order | Larger boxes drawn first, smaller on top, so small items such as windows are clickable inside walls |
| States | `normal`, `hovered`, `selected`, `locked` (lock icon), `unsupported` (dashed outline) |
| Badges in list | "Customisable" (supported) or "Not customisable"; "Edited by you" (locked); "Added by you" (origin user) |
| Hover link | Hovering a list row highlights its box and vice versa |
| Filter | Toggle **Customisable / All** (default All). Filtering hides unsupported boxes and rows. |
| Summary | "{n} regions, {k} customisable" |
| Confidence | Components with `confidence < 0.5` show a small "Check this" hint |

### 5.3 Interactions

| Action | How | API call |
|--------|-----|----------|
| Select | Click a box or list row | none |
| Change type | Dropdown in the detail panel (vocabulary and type-level `supported` values from `GET /api/client-config`; unsupported types are suffixed "(not customisable)") | `PATCH { type }` |
| Rename | Text field in the detail panel, saved on blur or Enter | `PATCH { label }` |
| Redraw box | Select a component, press **Redraw box**, drag a new rectangle on the photo | `PATCH { box }` |
| Add region | Press **Add region** (toolbar), drag a rectangle; a pending box appears with a small form (type dropdown defaulting to the last used type or `wall`, label optional); **Add** confirms, **Cancel** discards | `POST` |
| Delete | **Delete** button in the detail panel or row; always confirm with "Deleting this region also removes any material choices and measurement attached to it." | `DELETE` |
| Detect again | Toolbar button; confirmation text defined in `07` section 10.3 | `POST .../detect` |

Rules:
- Drawing uses pointer events (mouse and touch). A drag smaller than 1.5% in either dimension is ignored with the hint "Drag a larger area."
- Escape cancels drawing or a pending box. The pointer cursor changes to crosshair in drawing mode.
- Boxes cannot be moved or resized by dragging in the prototype; **Redraw box** is the adjustment method.
- While a request is in flight the affected row shows a small spinner and its controls are disabled.
- After each successful write, the store's `components` is updated from the response. Show the server-returned `warnings` as an amber toast. The editor does not duplicate compatibility checks in JavaScript or refresh data through selection/measurement HTTP endpoints; downstream screens load their current data when entered.
- Before every type change, show a generic confirmation without predicting which selections are incompatible: "Changing the type may remove material choices that are not compatible. Continue?" The server's returned warning is authoritative about what was removed.

### 5.4 Keyboard-accessible alternative

The region list is fully operable without drawing: rows are focusable, Enter selects, the type dropdown, label field and Delete button work with the keyboard. Drawing a new region is pointer-only; keyboard users can add a region through **Add region (numeric)**, a small form with four percentage fields (left, top, width, height) that creates a component through the same `POST`.

### 5.5 Data loaded on entering the screen

`components` and the client config. The editor does not load or depend on variant, selection, or measurement endpoints. Delete confirmation is unconditional and explains the server-side cascade. The catalogue's compatibility lookup is loaded by the backend and its results are reflected in each component's returned `supported` field.

### 5.6 Moving on

**Next: Choose materials** is always enabled (`03` section 10). If no component is customisable, a confirm dialog appears: "No customisable regions yet. You can add a wall region first, or continue anyway." Navigating sets `last_step = materials` (`03` section 3).

## 6. Validation and error handling

| Case | Result | User-facing handling |
|------|--------|----------------------|
| Invalid type, label or box in a request | `422 VALIDATION_ERROR` with `details.fields` | Inline field error |
| Photo, component or project not found | `404 NOT_FOUND` | Toast; the list is reloaded |
| Component limit reached | `409 CONFLICT` (`component_limit`) | Toast; **Add region** disabled |
| Concurrent edit in another tab | Last write wins | Reloaded on next mount |
| Drawn box partially outside the image | Client clamps to the image before sending; server clamps within tolerance | None |
| Network error | `ApiError` per `03` | Toast; local state unchanged; control re-enabled |
| Edit of a component deleted elsewhere | `404` | Toast "This region no longer exists"; list reloaded |

All errors use the standard format (`02` section 2).

## 7. Acceptance criteria

- Adding a region creates a component with `origin = "user"` and `is_locked = true`; it appears on the photo and in the list immediately and survives a page reload.
- Editing the type, label or box of an AI component sets `is_locked = true`; re-detection (`07`) does not change or delete it.
- Editing with identical values returns `200` and leaves `is_locked` unchanged.
- Changing a `wall` with a paint selection to `window` removes the selection, returns `removed_selections: 1` and shows a warning; changing it to `pillar` keeps a compatible selection (per the catalogue) and removes an incompatible one.
- Changing a component's box deletes its `ai_estimate` measurement but keeps a `user` measurement and warns.
- Deleting a component removes its selections and measurement; deletion always asks for confirmation and explains those cascades.
- `supported` is true for types with catalogue materials and false for `window`, `door` and `other` (given the default catalogue), and is derived on every read.
- Boxes remain aligned with the photo when the window is resized; smaller boxes inside larger ones remain clickable.
- A drag smaller than 1.5% creates nothing.
- The 61st component on a photo returns `409 CONFLICT` with `component_limit`.
- A keyboard-only user can retype, rename, delete and add (numeric form) components.
- All endpoints return the standard error format; no response exposes internal paths or stack traces.
