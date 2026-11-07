# 14 - Material Customization UX Improvement

**Purpose:** make the existing Materials and Redesign experience easier for a homeowner to understand and use, without changing the application's architecture or adding new AI capabilities.

**Status:** supplemental implementation specification for the existing MVP.

**Depends on:** `03-frontend-foundation.md`, `09-catalogue-and-selection.md`, `10-redesign.md`.

**Owns:** the interaction and presentation improvements described here, plus the narrowly scoped redesign-prompt wording change in section 7.

**Does not replace:** `01` (data model), `02` (API contracts), `04` (backend architecture), `09` (catalogue/selection business rules), or `10` (generation lifecycle and fingerprint rules). Those remain authoritative.

---

## 1. Goal and MVP boundary

The homeowner should be able to do this without learning technical terms or navigating several controls:

**Click a house region → see compatible choices immediately → choose a material → optionally choose a colour → see the saved choice on the house.**

The redesign preference field should also make it clear that free-text preferences refine the selected regions; they do not silently change unselected parts of the house or override an explicitly selected material/colour.

This is a focused UX and prompt-behaviour improvement. It is not a redesign of the application architecture.

### In scope

- Make image-region selection and the region list feel like one interaction.
- Make the customization panel clear, compact, responsive and easy to scan.
- Improve material cards with visual swatches/texture previews using existing catalogue fields.
- Make supported colour options discoverable and easy to use.
- Make save feedback and bulk application clearer.
- Clarify the Redesign preferences field and strengthen its prompt semantics.
- Add focused tests for the new interaction and prompt behaviour.

### Explicitly out of scope for this MVP

- No new frontend framework, state-management library, image service, or paid asset library.
- No AI material recommendations or natural-language-to-catalogue parser.
- No new database tables, columns, migrations, endpoints, or request fields.
- No arbitrary colour override for material categories that the current backend does not allow to have a `color_hex` parameter.
- No landscaping/scene-edit toggle in this iteration. Plants, trees, road, pavement, vehicles and other unselected surroundings remain protected by the existing redesign rules.
- No segmentation masks, inpainting, 3D reconstruction, or automatic structural verification.

---

## 2. Current implementation to preserve

The existing implementation already provides these behaviours and must be reused:

1. `materials.js` selects a supported component when the user clicks either a component box through `ImageStage.onBoxClick` or a row in the region list.
2. The Materials screen fetches the catalogue once and filters compatible materials locally for the selected component type.
3. `PUT /api/projects/{project_id}/variants/{variant_id}/selections/{component_id}` saves a selection. `DELETE .../selections/{component_id}` clears it.
4. `applyToAll` applies the saved choice to other supported components of the same type using the existing endpoint sequentially. Keep this behaviour; there is no bulk API.
5. `params.color_hex` is currently allowed only for `paint` and `texture` materials. The service validates this rule. Do not bypass or weaken server validation.
6. Selection notes and colour parameters are already included in the redesign prompt and generation fingerprint through the existing selection data.
7. `extra_instructions` is already stored per generation and included in the existing fingerprint.

Do not duplicate these services or introduce parallel selection state on the server.

---

## 3. Component-driven selection interaction

### 3.1 Selecting a region

- On entering Materials, select the first supported region as today.
- Show a short instruction near the photo: **“Click a highlighted area or choose a region from the list to customize it.”**
- Clicking any supported box on the photo or its corresponding list row must select the same component and update the side panel immediately.
- The selected box must have a visually distinct outline/fill and the selected list row must be highlighted.
- The side panel heading must show the component label and type, plus its current material (or **“No material selected yet”**).
- Keep unsupported regions visible in the image using the existing muted/dashed treatment. They must remain non-actionable and must not display material choices.
- Switching components must not change the active design variant or lose already-saved choices.
- Do not reload the project, photo, or catalogue when the user simply switches components. Use the current in-memory store.

### 3.2 Region list

- Keep the list as the keyboard-accessible alternative to clicking image boxes.
- Each row shows: component label, readable type, selected material name or **“Choose material”**, and a small status indicator.
- Clicking a row selects that component and brings its customization panel into view where needed.
- Preserve the current component ordering from the Components screen.

---

## 4. Material customization panel

### 4.1 Layout

Desktop:

- Keep the house image and region list in the left content column.
- Keep the customization panel in the right column.
- Make the customization panel sticky within the page where practical, with its own bounded scroll area only when necessary.
- Avoid multiple nested scroll areas. The user should not have to scroll both the page and a small card list to understand the available options.

Mobile:

- Stack the photo, region list and customization panel in one column.
- After a region is selected, scroll the customization panel into view without hiding the selected region context.
- Do not introduce a complex drawer library. Use responsive CSS and existing screen patterns.

### 4.2 Compatible material cards

Show only materials compatible with the selected component type, using the existing catalogue compatibility response/data.

Each card should show:

- A larger visual swatch/finish preview based on the existing `swatch_hex` and `category`.
- Material name and category.
- A short appearance description based on the existing `prompt_description` where suitable.
- A clear selected state (checkmark or selected border) for the saved material.
- The pricing unit in small text (`per sq ft` or `per running ft`).
- Maintenance and durability information inside a collapsed **Details** disclosure so long descriptions do not make every card tall.

Use CSS swatches or subtle category-based patterns for paint, stone, tile, wood, panel and railing finishes. Do not fetch external images and do not add a new `image_url` field to the catalogue for this iteration.

Category filter chips remain available, but **All** is the default. Keep the filters compact and make the active filter obvious.

### 4.3 Material selection and confirmation

- Clicking a material card continues to save that choice immediately through the existing selection API; do not add a second Apply button or a separate unsaved-selection workflow.
- After a successful save, show a brief, non-blocking confirmation such as **“Sandstone cladding applied to Front exterior wall.”**
- The selected card, region list row and photo overlay must update from the saved response/store.
- On API failure, keep the last saved choice visible and show the standard error toast; do not display the failed choice as saved.
- Keep **Clear choice** available when a saved selection exists.
- Keep **Apply this choice to all {type} regions** for compatible regions of the same type. Before applying, show a short confirmation naming the target count. Keep the existing sequential calls and progress feedback; summarize any partial failures.

---

## 5. Colour selection

### 5.1 Materials that support custom colour

The current backend explicitly allows `params.color_hex` only for catalogue categories `paint` and `texture`. Preserve that rule for this MVP.

For `paint` and `texture` materials:

- Show colour controls immediately after the material is selected.
- Show a small set of useful preset swatches plus the native browser colour input.
- Show the current HEX value in a readable text field; validate `#RRGGBB` before saving.
- Make the material's catalogue `swatch_hex` the initial/default colour.
- Clearly show whether the user is using the default material colour or a custom colour.
- Saving a colour must use the existing selection PUT and existing `params.color_hex` field.

For other material categories (stone cladding, tiles, panels, wood finish, glass railing, metal railing):

- Show the catalogue's material swatch/finish preview.
- Do not show an enabled custom HEX field, because the current API/service rejects `color_hex` for those categories.
- Show a short hint: **“This finish uses the material's natural colour. Choose another compatible finish to change its tone.”**

Do not silently send a `color_hex` parameter for a category that does not support it.

### 5.2 Colour preset rules

- Preset swatches are convenience shortcuts, not a closed list; the HEX picker remains available for any valid `#RRGGBB` colour on supported categories.
- Show a visible selected ring/checkmark on the current colour.
- Colour changes must update the region overlay tint and selection summary after the server confirms the save.

---

## 6. Selection notes and bulk actions

- Keep the optional per-selection note, but label it clearly: **“Note for this selected region (optional)”**.
- Keep the existing 100-character limit and save behaviour. The note should be described as contextual guidance for the selected surface, not a general instruction for the whole house.
- Keep bulk application limited to the same component type and supported components.
- The bulk confirmation must tell the user how many other regions will be updated. Do not change the bulk operation into a new endpoint.

---

## 7. Redesign preferences and prompt behaviour (`rd-v2`)

### 7.1 Redesign screen wording

Rename the free-text field from **“Optional design preferences”** to **“Additional preferences for the selected areas (optional)”**.

Use helper text and placeholder:

> Describe how the selected areas should look. For example: “Make the selected wall finish a little darker and give the facade a warm, premium appearance.”

Explain visibly:

> These preferences refine the materials you selected. They do not change unselected regions or the house structure.

Do not imply that free text can add plants, move gates, change windows, or redesign unselected parts of the scene in this MVP.

### 7.2 Prompt precedence

Update the prompt builder with a new prompt version `rd-v2` and make the precedence explicit:

1. Structural preservation rules are mandatory and cannot be overridden.
2. The selected material in each CHANGES line must be applied to that listed region.
3. If the selection contains an explicit `color_hex`, that exact colour takes priority over any conflicting free-text colour suggestion.
4. If no explicit colour is selected and the homeowner asks for a shade/tone adjustment, the model may refine the appearance of the already-selected material on the listed CHANGES region only.
5. Free-text preferences must never change material identity, add a new edit region, or modify a component in KEEP UNCHANGED.
6. The image model must ignore requests to alter landscaping or other unselected surroundings in this MVP. Existing plants, trees, ground, road, pavement, vehicles and neighbouring properties remain unchanged.

The preference block should be phrased as styling guidance for the already-selected CHANGES regions, not as a lower-priority instruction that is always ignored. It must still state that it cannot override the rules above.

### 7.3 Fingerprint and staleness

- Set `REDESIGN_PROMPT_VERSION = "rd-v2"`.
- Keep the current fingerprint inputs and canonical serialization. `extra_instructions` is already part of the fingerprint; selected material and `params.color_hex` are already included in `edits`.
- Do not remove or weaken the existing keep-set fingerprint coverage.
- The prompt-version change must make generations created under `rd-v1` report `is_stale = true` when read under `rd-v2`.
- No database migration is required for this change.

---

## 8. API and data constraints

For this MVP, no endpoint or database changes are required.

Reuse:

- `GET /api/catalogue` and cached catalogue data.
- Existing component list and component IDs.
- Existing `PUT` and `DELETE` selection endpoints.
- Existing `SelectionData.params.color_hex` and `params.note`.
- Existing generation request `extra_instructions` field.
- Existing `generations.prompt_text`, `input_fingerprint`, and prompt-version handling.

If implementation discovers a requirement that truly cannot be represented by these contracts, stop and report the specific gap instead of silently adding a new schema/API.

---

## 9. Automated tests

Add focused tests using the existing test tools and patterns. Do not migrate the project from `unittest`/Node's built-in test runner to `pytest` for this small feature.

Frontend tests must cover:

1. Clicking an image box selects the same component as clicking its list row.
2. The side panel shows the selected component's label, type and current material state.
3. Only compatible materials are rendered.
4. The saved material is visibly selected.
5. A successful material save updates the region summary/overlay and gives confirmation.
6. A failed save does not show the unsaved material as selected.
7. Colour controls appear for paint/texture and not for unsupported categories.
8. Preset and custom HEX colours are sent through the existing selection payload.
9. Mobile layout stacks the panels and keeps controls usable at narrow widths.

Backend/redesign tests must cover:

1. The prompt version is `rd-v2`.
2. A selected wall with no explicit colour plus a “make the selected wall darker” preference permits a darker appearance while retaining the selected material identity.
3. An explicit `color_hex` takes priority over a conflicting free-text colour preference.
4. Preferences cannot change components in the KEEP list or alter structural-preservation requirements.
5. A preference requesting new plants/landscaping does not remove the preserve-scene instruction in this MVP.
6. The fingerprint changes when `extra_instructions` or selected `color_hex` changes.
7. Existing `rd-v1` generations are reported stale under `rd-v2`.
8. All existing keep-set fingerprint tests continue to pass.

---

## 10. Acceptance criteria

- A user can click a supported region on the house image or select it from the list and immediately see the correct customization panel.
- The selected region is clearly highlighted in both the image and list.
- The user can scan compatible materials quickly without reading every maintenance/durability paragraph.
- A selected material is visibly reflected in the component row and the house overlay.
- Paint and texture users can choose a preset colour or any valid HEX colour; other material categories do not expose a misleading custom-colour control.
- The Materials screen is usable on desktop and mobile without excessive nested scrolling.
- The free-text redesign preference can refine only the selected CHANGES surfaces and cannot override explicit material/colour choices or structural preservation.
- Existing selections, variants, generation history, estimation, PDF reports and API contracts continue to work.
- The complete existing backend and frontend test suites pass, together with the new focused tests.

---

## 11. Implementation boundaries and delivery

- Implement this spec as a focused change to `frontend/static/js/screens/materials.js`, `frontend/static/css/components.css`, `frontend/static/js/screens/redesign.js`, `backend/app/services/redesign_service.py`, and only the test files needed.
- Modify other files only if an existing contract requires it; explain any such change.
- Do not edit specs `00` to `13` as part of implementation.
- Do not change the AI provider, model IDs, image dimensions, database schema, or estimation/report business logic.
- Do not implement landscaping generation, an AI recommendation engine, or a new catalogue image service.
- After implementation, run the complete backend and frontend suites and verify the flow: select a region → choose a material → customize colour where supported → save → generate a new redesign → verify `rd-v2` prompt and staleness.
