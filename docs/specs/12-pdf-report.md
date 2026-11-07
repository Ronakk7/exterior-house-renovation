# 12 - PDF Report

**Purpose:** generating, storing and downloading the PDF report: content, layout, data sources, behaviour when parts are missing, and the Report screen. The report must work as a discussion document with contractors (PDF 5.8).
**Depends on:** `01-data-model.md`, `02-api-contracts.md`, `04-backend-foundation.md`, `06-project-and-upload.md`, `07-component-detection.md`, `09-catalogue-and-selection.md`, `10-redesign.md`, `11-estimation.md`.
**Endpoints owned (from `02`):** #39 create report, #40 list reports, #41 download.
**Enables:** `13` (final deliverable and demo).

---

## 1. Scope

In scope: report data assembly, PDF rendering, region map image, storage, report records, download, Report screen.
Out of scope: report templates or branding, multiple languages, editing the PDF, emailing, HTML or Word export, embedding the comparison slider, charts.

## 2. Principles

1. **Same numbers as the screen.** The report calls the same estimate service as `GET .../estimate` (`11` section 5.6) in-process. It never recomputes money itself and never calls an AI model.
2. **A report always says what it is made of.** It states whether the redesigned image is approved, outdated or missing, which measurements are the user's and which are AI estimates, and which rates are defaults.
3. **Honest and self-contained.** Assumptions, limitations and the advisory disclaimer are part of every report (`00` section 7 assumptions).
4. **Pure assembly, then rendering.** Data is first assembled into a plain report model (a dictionary); a separate step renders it to PDF. The model step is fully testable without a PDF.

## 3. Technology choice (allowed by `04` section 1)

| Need | Choice |
|------|--------|
| PDF drawing from Python code | **ReportLab** (pure Python, no system packages, which avoids deployment problems that HTML-to-PDF converters have) |
| Image handling | The image library already used by `06` and `05` |
| Fonts | The built-in standard fonts only (no font files) |
| Test-only | A PDF text-extraction library may be used in tests to read generated PDFs; it is not a runtime dependency |

New runtime dependency to add to `requirements.txt`: ReportLab (pinned at implementation time, `04` section 10).

**Consequence of standard fonts:** they do not contain the rupee sign or non-Latin letters. Therefore:
- Money is written as `{currency code} {number}`, e.g. `INR 1,07,510.00` (Indian digit grouping when the currency is `INR`, otherwise thousands grouping).
- All user-entered text (project name, labels, notes) and catalogue text is converted to Latin-1; characters outside it are replaced by `?`.

## 4. Endpoint behaviour

### 4.1 POST `/api/projects/{project_id}/reports`

Request (`02` section 5.11): `{ "variant_id"?, "generation_id"? }`. Synchronous; returns `201` Report.

| # | Step | Failure |
|---|------|---------|
| 1 | Project exists | `404` |
| 2 | Variant: `variant_id` or the project's active variant; must belong to the project | `404` |
| 3 | The project has a photo | `409 NO_PHOTO` |
| 4 | The variant has at least one selection | `409 NO_SELECTIONS` |
| 5 | Resolve the redesign image (4.2) | provided generation invalid: `404` or `409 CONFLICT` (`generation_not_succeeded`) |
| 6 | Insert a stage run (`stage = "report"`, `running`), commit | |
| 7 | Assemble the report model (section 5) | |
| 8 | Render the PDF to memory (section 6) | exception: stage run `failed`, `500 INTERNAL_ERROR`, no file and no row left |
| 9 | Save to `projects/{project_id}/reports/{report_id}.pdf`; in one transaction insert the `reports` row (`variant_id`, `generation_id` or null, `pdf_path`, `grand_total`, `currency`), complete the stage run, touch the project | on failure delete the saved file |
| 10 | Return `201` Report with `download_url` | |

### 4.2 Resolving the redesign image

1. If `generation_id` is given: it must belong to the project **and the chosen variant** (else `404`), and be `succeeded` (else `409 CONFLICT`, `generation_not_succeeded`).
2. Otherwise: the approved, succeeded generation of the variant; else the newest succeeded generation of the variant; else **none**.
3. If the generation row exists but its file is missing: treat as none and log a warning.

A report without a redesign image is valid: it shows a placeholder and a note (section 5.1).

### 4.3 Other endpoints

| Endpoint | Behaviour |
|----------|-----------|
| GET `.../reports` | `{ "items": [Report] }`, newest first |
| GET `.../reports/{rid}/download` | `application/pdf`, `Content-Disposition: attachment; filename="renovation-report-{slug}.pdf"` where `slug` is the project name lower-cased, non-alphanumerics replaced by `-`, collapsed, max 40 characters, default `project`. `404` if the report or file is missing. Headers per `04` section 6. |

Reports are never regenerated or modified; generating again creates a new report. There is no delete endpoint (not in `02`); reports are removed when the project is deleted.

## 5. Report model (assembled data)

All values come from the database, the catalogue and the estimate service; nothing is typed by hand.

### 5.1 Fields

| Section | Content | Source |
|---------|---------|--------|
| Header | App name, "Exterior Renovation Plan", project name, design (variant) name, generated date and time (UTC, with "UTC"), report ID short form | project, variant |
| Summary | Grand total with range, currency, number of regions with materials, number of measurements from the user and from AI, number of missing measurements | estimate |
| Photos | Original photo (upright, downscaled); redesigned image with status text; region map | photo, generation |
| Materials | One row per selected component: Region number, region label, type, material, category, colour (swatch and hex if custom) and note | selections, components, catalogue |
| Material notes | One row per distinct material used: maintenance note, durability note | catalogue |
| Quantities | One row per estimate line: region number, material, measure and unit, wastage %, quantity with wastage, approximate purchase quantity, measurement source | estimate |
| Costs | Line table (material cost, labour cost, line total, range), category subtotals, grand total and range | estimate |
| Rates used | Distinct materials in the estimate: material rate, labour rate, wastage %, "default" or "edited" | estimate and rates |
| Not included | Selections without a usable measurement | estimate `missing_measurements` |
| Assumptions and limitations | Fixed text (section 7) plus conditional notes (5.2) | fixed |
| Disclaimers | The estimate's `disclaimers` | estimate |

**Redesign status text:**

| Condition | Text under the image |
|-----------|---------------------|
| Approved and not stale | "AI-generated preview. Approved by the homeowner." |
| Succeeded, not approved, not stale | "AI-generated preview. Not yet reviewed or approved." |
| Stale (`10` section 6.2) | "AI-generated preview. OUTDATED: materials or regions were changed after this image was created." |
| None | Placeholder box with "No redesigned image was generated for this design." |

Every redesigned image also has the caption "AI-generated image. Colours, textures and details can differ from real materials."

### 5.2 Conditional notes (added to the limitations section)

- AI estimates present: "Measurements marked AI estimate come from an AI reading of the photo and may be inaccurate by 25% or more."
- Missing measurements: "The regions listed under Not included have no measurement and are excluded from totals."
- Default rates used: "Rates marked default are placeholders, not market prices."
- Outdated image: the stale sentence above.

### 5.3 Region numbers and the region map

- Selected components are numbered `1..n` in the order of the estimate's `line_items` (and then any remaining selected components without a usable measurement, in component order).
- The **region map** is the original photo with a rectangle and number drawn for every numbered component (box colour per type, number in a filled label). It lets contractors match table rows to places on the house. It is drawn with the image library at report time and is not stored.
- Should-have, not mandatory: if drawing fails, the report is produced without it and a warning is logged.

### 5.4 Image preparation for the PDF

| Image | Rule |
|-------|------|
| Original | Read from storage, apply EXIF orientation (`06` section 4.1), downscale so the long side is at most 1600 px, convert to JPEG quality 85, no metadata |
| Redesigned | Same, from the generated PNG |
| Region map | Built from the prepared original |
| Resulting PDF size | Expected under 5 MB; the long-side cap is lowered to 1200 px if the PDF would exceed 8 MB |

## 6. Layout (A4 portrait, standard fonts)

Margins 18 mm. Body text 10 pt; table text 8.5 pt; headings 14 and 11 pt bold. Numbers right-aligned in tables. Colours: dark text, one accent colour for headings and table headers, amber for approximation notes.

| Page area | Content |
|-----------|---------|
| Page 1 | Header block; summary box (grand total and range, counts); original and redesigned images side by side (stacked if the photo is portrait), each with caption and status text |
| Page 2 | Region map; materials table; material notes table |
| Following pages | Quantities table; cost table with category subtotals and grand total; rates used; not included list |
| Last page | "How these estimates were made" (section 7.1) and "Limitations" (section 7.2); disclaimers |
| Every page footer | "Advisory estimate - not a quotation" left; "Page x of y" right; project ID short form centre |

Rules:
- Tables break across pages with the header row repeated; a row is never split across pages.
- Long text in a cell wraps; labels are truncated to 60 characters with an ellipsis in tables only.
- Currency formatting: `INR 1,07,510.00` (see section 3); ranges as `INR 88,661.90 - INR 126,358.10`.
- Approximation is shown with the word "approx." next to totals and with the badge text `AI estimate` or `Your value` next to each measurement source.

## 7. Fixed documentation text in the report

### 7.1 How these estimates were made

Reproduces the five points of `11` section 8.1 in plain language.

### 7.2 Assumptions and limitations

- The building is a residential low-rise building; only exterior renovation is considered; no structural engineering is included (PDF section 7).
- Estimates are advisory, not a binding quotation.
- The redesigned image is an AI-generated preview. It is not a drawing, may differ from the real house in small details, and was **not** used for any measurement.
- Surface areas rely on approximate measurements entered by the homeowner or estimated by AI from a single photograph with no known scale.
- Perspective, hidden or curved surfaces are not modelled; overlapping regions may be counted twice if measured twice.
- Default rates and wastage allowances are placeholders; real prices differ by location, supplier and time.
- Exclusions: scaffolding, surface preparation, repairs, taxes, transport.
- Ranges are sums of per-line uncertainties, not statistical confidence intervals.
- Please verify all dimensions on site before ordering materials.

(The limitations of `11` section 8.2 are the same list; the report uses this version.)

## 8. Report screen (`report.js`)

### 8.1 Data loaded

`project`, `variants`, `generations` (active variant), `estimate` (active variant), `reports`, `measurements`. Prerequisite panel when there is no photo or the active variant has no selections.

### 8.2 Layout

```
+-----------------------------------------------------------+
| Design: [Design 1 v]                                       |
| Redesign image: [ Approved - 6 Nov 15:20  v ]  (or note)   |
+-----------------------------------------------------------+
| Readiness                                                  |
|  OK    Photo                                               |
|  OK    Materials chosen (6 regions)                        |
|  WARN  Redesign image is outdated / missing                |
|  WARN  2 regions have no measurement (not in totals)       |
|  WARN  3 measurements are AI estimates                     |
|  INFO  Default placeholder rates are used                  |
+-----------------------------------------------------------+
| [ Generate PDF report ]                                    |
+-----------------------------------------------------------+
| Previous reports: date | design | total | [Download]        |
+-----------------------------------------------------------+
| [Back: Estimate]                                           |
+-----------------------------------------------------------+
```

### 8.3 Behaviour

| Element | Behaviour |
|---------|-----------|
| Design selector | Changing it updates the active variant (as in `09`) and the readiness checks |
| Redesign image selector | Lists succeeded generations of the design (newest first, with Approved/Outdated labels). Default: approved, else newest. If none exist it shows "No redesign yet. The report will say so." and the request omits `generation_id`. The request also omits `generation_id` unless the user changed the default. The prototype has no way to leave out an existing image (the request shape in `02` cannot express it). |
| Readiness checks | Computed on the client from the store: counts of selections, measurements (sources), missing measurements (from `estimate.missing_measurements`), staleness of the chosen generation, and whether all rates are default. Warnings do not block generation. |
| Generate | Primary button. Busy overlay "Preparing your report..." (`03` section 8.1). On success the new report appears at the top of the list and the browser starts the download through `download_url`. |
| Previous reports | List with date, design name (or "Deleted design"), grand total (with currency) and **Download**. |
| Errors | `NO_PHOTO` / `NO_SELECTIONS`: prerequisite panel. `INTERNAL_ERROR`: toast "We could not create the report. Please try again." with a retry button. |

## 9. Failure scenarios

| Scenario | Outcome |
|----------|---------|
| No redesign exists | Report produced with placeholder; readiness shows a warning |
| Generated image file missing | Treated as no image; warning logged |
| Original image file missing | `500 INTERNAL_ERROR`; no partial report (the original is required) |
| PDF rendering raises an error | Stage run `failed`; no file, no row; `500 INTERNAL_ERROR` |
| Disk write failure | Same; any partial file removed |
| Variant has measurements missing | Report produced; "Not included" section lists them; totals exclude them |
| Very long labels or notes | Truncated in tables, wrapped in text |
| Characters outside Latin-1 in labels | Replaced by `?` |
| Two reports requested simultaneously | Both succeed with separate IDs and files |
| Project deleted during generation | The insert fails; the saved file is removed |

## 10. Dependency notes

- **`02` section 3.10** has no `variant_name` in the Report object; the client matches `variant_id` against `variants` and shows "Deleted design" when null or unknown.
- **`02` section 5.11** cannot express "no redesigned image" explicitly; the screen does not offer it (see 8.3). No contract change is made here.
- **`10` section 6.2** defines `is_stale`, reused here; **`11`** provides the estimate service and disclaimers; **`09`** provides notes, categories and colours.
- Reading the **original** photo and **components** (`06`, `07`, `08`) is read-only.

## 11. Acceptance criteria

- With a project having a photo, selections and measurements (mock mode), `POST .../reports` returns `201`, the PDF exists in `projects/{id}/reports/`, and the download returns `application/pdf` with the expected filename.
- The PDF contains: the original image, the redesigned image (or the placeholder), the materials table, the quantities table, the cost table with category subtotals, grand total and range, rates used, the limitations section and the footer on every page.
- The grand total printed in the PDF equals `grand_total` from `GET .../estimate` at generation time and `reports.grand_total`.
- AI-estimated measurements are labelled `AI estimate`; a stale redesign is labelled OUTDATED; missing measurements appear under "Not included".
- A report for a variant with no redesign still generates.
- A label containing a non-Latin character does not crash the generator.
- A 4000 x 3000 photo yields a PDF under 8 MB.
- Generating twice yields two reports with different IDs; both download.
- A failure inside rendering leaves no row in `reports` and no file on disk.
- No AI call is made while creating a report.

## 12. Automated test cases

| # | Test | Expected |
|---|------|----------|
| 1 | Report model for a full project (photo, 3 selections, measurements, approved generation) | All sections present; totals equal the estimate |
| 2 | Report model without generation | `redesign` section is the placeholder |
| 3 | Report model with a stale generation | Status text contains OUTDATED |
| 4 | Report model with an AI-estimate line | Source shows `AI estimate`; conditional note present |
| 5 | Report model with a missing measurement | Appears in Not included; excluded from totals |
| 6 | Money formatting for INR | `107510` renders `INR 1,07,510.00`; `0.5` renders `INR 0.50` |
| 7 | Latin-1 sanitation | "Café 🏠" becomes "Café ?" |
| 8 | Slug function | "My House #1!" becomes `my-house-1`; empty name becomes `project` |
| 9 | PDF render (test environment) | Parses; page count >= 3; extracted text contains the project name and the grand total string |
| 10 | POST with `generation_id` of a failed generation | 409 `generation_not_succeeded` |
| 11 | POST with `generation_id` belonging to another variant | 404 |
| 12 | POST for a variant without selections | 409 `NO_SELECTIONS` |
| 13 | Rendering error (monkeypatched) | 500, no row, no file, stage run `failed` |
| 14 | Region map with 12 regions | Image produced with the expected size |
| 15 | Download unknown report ID | 404 |
| 16 | Delete project | Report files removed |
