# 03 - Frontend Foundation

**Purpose:** the shared structure and conventions of the plain HTML/CSS/JavaScript frontend: page layout, routing, workflow stepper, API client, state, loading/error display and image-overlay conventions. Individual screens are specified in the feature specs.
**Depends on:** `02-api-contracts.md` (and, through it, `01`).
**Used by:** `06`, `08`, `09` (screens), and by `10`, `11`, `12` for their screens.

---

## 1. Principles

1. **No framework, no build step.** Plain HTML, CSS and ES-module JavaScript served as static files by the FastAPI app. Opening the site must work with no install beyond the backend.
2. **Single page, hash routing.** One `index.html`; screens are swapped in and out of one container.
3. **Backend is the source of truth.** The frontend keeps a small in-memory cache and re-fetches after changes. Nothing important lives only in the browser.
4. **Non-technical users.** Plain language, one clear primary action per screen, visible progress, forgiving errors.
5. **No hard-coded domain data.** Component types, limits and currency come from `GET /api/client-config`; materials from the catalogue endpoints.
6. **Plain-language honesty.** Approximate values and AI-generated content are labelled wherever they appear (`00`, rule 6).

## 2. File layout

```
frontend/
  index.html                  shell: header, stepper, main container, toast area, busy overlay
  static/
    css/
      tokens.css              design tokens (variables)
      base.css                reset, typography, layout, forms, buttons, tables
      components.css          stepper, cards, toasts, overlay, image stage, slider, badges
    js/
      main.js                 entry: boot, route handling
      api.js                  all HTTP calls, error normalization
      store.js                in-memory state and change events
      router.js               hash router
      ui.js                   toast, busy overlay, confirm dialog, formatters, DOM helpers
      stepper.js              workflow stepper
      imagestage.js           image + overlay helper (box drawing, box rendering)
      screens/
        projects.js           project list (home)
        upload.js             step 1
        components.js         step 2
        materials.js          step 3
        redesign.js           step 4
        estimate.js           step 5
        report.js             step 6
```

Each screen module exports `mount(container, ctx)` and `unmount()`. `ctx` provides `store`, `api`, `ui`, `router`, `projectId`. Feature specs define what each screen does; this file defines the contract and shared helpers. Backend serving of this folder is owned by `04`.

## 3. Routing

Hash-based, so no server rewrite rules are needed.

| Route | Screen |
|-------|--------|
| `#/` | Project list |
| `#/p/{project_id}/upload` | Step 1 Upload |
| `#/p/{project_id}/components` | Step 2 Components |
| `#/p/{project_id}/materials` | Step 3 Materials |
| `#/p/{project_id}/redesign` | Step 4 Redesign |
| `#/p/{project_id}/estimate` | Step 5 Estimate |
| `#/p/{project_id}/report` | Step 6 Report |

Rules:
- `#/p/{project_id}` with no step redirects to the project's `last_step` (fallback `upload`).
- Opening a project whose ID does not exist shows a friendly "project not found" message with a link home.
- On entering a step the frontend calls `PATCH /api/projects/{id}` with `last_step` (fire and forget; failure is ignored silently).
- Navigating to a step whose prerequisites are missing is allowed but the screen shows a clear "do this first" panel with a button to the required step (see section 5). No silent redirects.

## 4. Page shell

```
+--------------------------------------------------------------+
| App name        Project name (editable)        [All projects] |
+--------------------------------------------------------------+
| (1) Upload > (2) Components > (3) Materials > (4) Redesign    |
|            > (5) Estimate > (6) Report                        |
+--------------------------------------------------------------+
|                                                              |
|                     screen content                           |
|                                                              |
+--------------------------------------------------------------+
| Footer: "Estimates are approximate and advisory."            |
+--------------------------------------------------------------+
```

- The stepper and project name are hidden on the project list screen.
- Responsive: usable from 360 px wide (stack panels vertically) up to desktop. Image stages scale to container width.
- Toasts appear top-right; the busy overlay covers only the main container, never the header.

## 5. Workflow stepper

Six steps map to the workflow in `00` section 9. States per step:

| State | Meaning | Visual |
|-------|---------|--------|
| `current` | The open screen | Filled, bold |
| `done` | Prerequisite data exists | Check mark |
| `available` | Reachable, not complete | Outlined |
| `locked-hint` | Missing prerequisite | Muted, still clickable; screen explains what is missing |

Completion rules (derived from the store, not stored):

| Step | Done when |
|------|-----------|
| Upload | project has at least 1 photo |
| Components | photo has a successful usable detection (`quality_usable = 1` and `detected_at` not null), whether or not any regions were found |
| Materials | the active variant has at least 1 selection |
| Redesign | the active variant has at least 1 succeeded generation |
| Estimate | at least 1 selected component has a measurement |
| Report | at least 1 report exists |

Prerequisite panels (shown inside the screen when missing): Components needs a photo; Materials needs components; Redesign needs selections; Estimate needs selections; Report needs selections. The panel shows one sentence and one button ("Go to Upload").

## 6. Store (in-memory state)

One module-level object, replaced when the project changes. Screens read from it and call `store.refresh*()` functions after API writes.

| Key | Content | Loaded |
|-----|---------|--------|
| `config` | `GET /api/client-config` | once at boot |
| `catalogue` | `GET /api/catalogue` | on first need, cached for the session |
| `project` | Project | on entering a project route |
| `photos` | Photo list | on entering a project route |
| `components` | Component list (for the project) | on entering step 2 and after any edit |
| `variants` | Variant list with selections | on entering step 3 and after any edit |
| `activeVariantId` | From `project.active_variant_id` | with `project` |
| `generations` | Generation list for the active variant | on entering step 4 |
| `measurements`, `rates` | Lists | on entering step 5 |
| `estimate` | Estimate for the active variant | on entering step 5 and after any measurement, rate or selection change |
| `reports` | Report list | on entering step 6 |

Rules:
- `store` emits a simple `change` event with the key that changed; screens re-render only their own parts.
- On a write, the screen uses the returned resource to update the store, then refreshes dependent data (e.g. after a selection change, refresh `estimate` if the estimate screen is visible; always mark local generations "may be outdated" by re-fetching).
- Switching the active variant calls `PATCH /api/projects/{id}` and refreshes `generations` and `estimate`.
- No data is persisted in `localStorage` except an optional list of recently opened project IDs (convenience only; the server list is authoritative).

## 7. API client (`api.js`)

- One function per endpoint in `02`, named after the operation (`createProject`, `uploadPhoto`, `detectComponents`, ...).
- Returns parsed JSON on success. On failure throws an `ApiError` with `code`, `message`, `details`, `request_id`, `status`.
- Network failure (no response) throws an `ApiError` with `code: "NETWORK_ERROR"` and the message "Could not reach the server. Check your connection and try again."
- Timeouts: ordinary calls 20 s. Detection and AI estimate: 75 s. Generation: 135 s. (Server timeouts are in `05`; the client values are 15 s longer.) A client timeout throws `ApiError` with `code: "CLIENT_TIMEOUT"` and the message "This is taking longer than expected. Please try again."
- File upload uses `FormData` with field `file`; no manual `Content-Type`.
- Image URLs from responses are used directly in `<img>` tags. Append a cache-busting query (`?v={updated_at or id}`) only when an image is replaced.
- Never log or display `request_id` prominently; show it in small text under error toasts ("Reference: req_...") so support can trace a problem.

## 8. Shared UI behaviours (`ui.js`)

### 8.1 Busy overlay for slow operations

Used for detection, generation and AI estimate.
- Shows a spinner, a plain-language message ("Analysing your house photo..."), and elapsed seconds.
- After 20 s adds "This can take up to a minute."
- Disables the triggering button; prevents double submission.
- Provides **no cancel** in the prototype. The request completes or times out.
- Always cleared in a `finally` path, whether success or failure.

### 8.2 Errors

| Situation | Display |
|-----------|---------|
| Field validation (`VALIDATION_ERROR` with `details.fields`) | Inline text next to the field; also a toast summary |
| Any other `ApiError` | Toast with the server `message`; red for failures, amber for AI-blocked/rate-limited |
| `AI_NOT_CONFIGURED` | Persistent banner on the screen: "AI features are not configured on this server." |
| `AI_*` failures | Toast plus a "Try again" button next to the action that failed |
| Unexpected JavaScript error | Toast: "Something went wrong. Please reload the page." Logged to the browser console |

Toasts auto-dismiss after 6 s for info/success; errors stay until closed.

### 8.3 Confirmations

A simple modal confirm for destructive actions: delete project, delete photo (explains dependents will be removed), delete generation, delete variant, re-run detection (explains that unedited AI results are replaced and edited ones are kept), deleting a component that has selections.

### 8.4 Formatters

- Currency: `Intl.NumberFormat('en-IN', { style: 'currency', currency: config.currency })`, no decimals in display for totals above 1000, two decimals for rates.
- Area: `1,234 sq ft`; length: `120 ft`; percentages: `8%`.
- Dates: local time, `6 Nov 2026, 3:15 pm`.
- Component type labels come from `config.component_types`.

### 8.5 Approximation labelling

Reusable badge component with fixed wording:
- `Approximate` (for ranges and estimates)
- `AI estimate` (for `source: "ai_estimate"` measurements)
- `Your value` (for `source: "user"`)
- `Outdated` (for stale generations)
- `AI-generated image` (on all redesign images, as a small corner badge)

## 9. Image stage and overlay conventions (`imagestage.js`)

Used by the Components screen (editing) and the Materials screen (read-only selection) and the Redesign screen (comparison).

- A wrapper `div` with `position: relative`, containing the `<img>` at 100% width and an overlay `div` of the same size.
- A component box is drawn as an absolutely positioned child of the overlay with `left/top/width/height` in **percentages** (`box.x * 100 + "%"` etc.). Percentages keep boxes correct when the image is resized. No canvas is used.
- Box colours are keyed by component `type` (a fixed colour map in `components.css`). A label chip shows the type label above the box's top-left corner.
- States: `normal`, `hovered`, `selected`, `locked` (small lock icon), `unsupported` (dashed outline, muted).
- Pointer coordinates are converted to normalized values with the wrapper's bounding rectangle: `x = (clientX - rect.left) / rect.width`, clamped to 0-1. Pointer events (mouse and touch) are used; drawing a box requires a drag of at least 1.5% in each dimension, otherwise it is treated as a click.
- The helper exposes: `renderBoxes(components, options)`, `enableDrawing(onDrawn(box))`, `select(componentId)`, and `onBoxClick(handler)`. Editing semantics (what drawing does) belong to `08`.
- Before/after comparison (owned by `10`) uses the same wrapper pattern with a draggable divider; the generated image is displayed with the same aspect ratio as the original (guaranteed by `10`).

## 10. Screen contract

Every screen:
1. On `mount`: shows a skeleton or spinner, loads what it needs via `store`, renders. If a prerequisite is missing, shows the prerequisite panel instead.
2. Contains exactly one primary button, styled distinctly, whose label is a verb ("Detect components", "Generate redesign").
3. Renders server errors via the shared handlers, never with its own error UI.
4. On `unmount`: removes event listeners and clears timers. No state remains in globals.
5. Provides "Back" and "Next" buttons to adjacent steps in the footer area of the screen. "Next" is always enabled; the next screen explains missing prerequisites.

Screen ownership of detailed behaviour:

| Screen | Specification |
|--------|---------------|
| Project list, Upload | `06` |
| Components | `07` (detect trigger, quality guidance) and `08` (editor) |
| Materials | `09` |
| Redesign | `10` |
| Estimate | `11` |
| Report | `12` |

## 11. Visual design (minimal)

- `tokens.css` defines colour, spacing, radius and font-size variables; light theme only.
- One accent colour for primary actions, neutral greys otherwise, amber for approximate/warning, red for errors.
- Body text at least 16 px; tap targets at least 40 px.
- Tables for line items and rates, with right-aligned numbers.
- Every image has an `alt` attribute ("Original house photo", "Redesigned house, AI-generated").
- Keyboard: all buttons and inputs reachable by Tab; modals trap focus and close on Escape. Box drawing is pointer-only; the editor also offers a list view of components with type dropdowns and delete buttons (`08`) as the keyboard-accessible alternative.

## 12. Error and edge behaviours

| Case | Behaviour |
|------|-----------|
| Browser refresh mid-screen | State reloads from the server; unsaved text inputs are lost, saved data is not |
| Backend unreachable | Persistent banner "Cannot reach the server" with a Retry button; screens keep showing cached data read-only |
| Two tabs on the same project | Last write wins; each screen refreshes its data on mount; no live sync |
| Very large or tall photo | Image stage scales to container width and the page scrolls vertically |
| Slow connection | Uploads show a progress bar; other calls use the busy overlay |
| Mock AI mode | When `config.ai_mock_mode` is true, a small banner "Demo mode: AI responses are simulated" is shown in the header |

## 13. Acceptance criteria

- The site works by opening the backend's root URL with no build step.
- Reloading on any `#/p/{id}/{step}` route restores the correct screen and data.
- All six steps are reachable; missing prerequisites produce a clear panel rather than an error or blank page.
- Every slow action shows the busy overlay and clears it on success, failure and timeout.
- A forced backend error (any code in `02`) displays a readable message; no raw JSON or stack trace appears.
- Component types, currency and upload limits shown in the UI match `GET /api/client-config` with no duplicate hard-coded lists.
- Box overlays stay aligned with the photo when the window is resized.
