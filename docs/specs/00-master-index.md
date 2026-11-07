# 00 - Master Index

**Project:** AI-Based Exterior House Renovation & Cost Estimation System
**Purpose of this file:** orientation, file map, build order, glossary, precedence rules, and the full mapping from the original assessment PDF (sections 1-9) to these specifications.
**Depends on:** nothing.

---

## 1. Project summary

A homeowner uploads a photograph of their house exterior. The system detects visible components (walls, windows, balconies, pillars, etc.), lets the user correct them, lets the user choose a material per component from a catalogue, generates a redesigned photograph of the same house, helps the user supply approximate dimensions, calculates quantities and costs with plain Python, and produces a downloadable PDF report. Projects are saved and can be reopened.

## 2. Architecture in one paragraph

One FastAPI application serves both a JSON API (`/api/...`) and a static HTML/CSS/JavaScript frontend. SQLite stores project data; the local file system stores uploaded images, generated images and PDF reports. Two separate AI capabilities are used, both through the same Google Gemini API account and key: a **vision model call** for component detection (and, optionally, approximate dimension estimates) and an **image-generation/editing model call** ("Nano Banana") for the redesign. All quantity and cost calculations are deterministic Python. There are no microservices, no autonomous agents, no segmentation or 3D models. Control flow is user-driven: the user moves between screens, and every AI call is a single, explicit request from the user.

## 3. Specification files

| # | File | Responsibility | Depends on |
|---|------|----------------|------------|
| 00 | `00-master-index.md` | This file: map, order, glossary, precedence, traceability | none |
| 01 | `01-data-model.md` | SQLite schema, IDs, enums, file layout, staleness rules | 00 |
| 02 | `02-api-contracts.md` | All endpoints, request/response shapes, error format | 01 |
| 03 | `03-frontend-foundation.md` | SPA structure, stepper, API client, shared UI conventions | 02 |
| 04 | `04-backend-foundation.md` | App entry, module layout, config, DB/storage access, errors, logging, CORS | 01, 02 |
| 05 | `05-ai-integration.md` | Two separate Gemini integrations (vision detection, image generation), shared rules, mock mode | 02, 04 |
| 06 | `06-project-and-upload.md` | Project CRUD, photo upload and validation | 01, 02, 03, 04 |
| 07 | `07-component-detection.md` | Detection call, schema, validation, quality flag | 01, 02, 05, 06 |
| 08 | `08-region-editor.md` | Review/correct screen and component edit logic | 01, 02, 03, 07; the catalogue compatibility foundation from 09 (implemented first) |
| 09 | `09-catalogue-and-selection.md` | Catalogue data, compatibility, selections, design variants | 01, 02, 03, 08 for selection integration; its compatibility foundation is independent of 08 |
| 10 | `10-redesign.md` | Prompt assembly, image generation, regenerate, comparison | 01, 02, 05, 06, 07, 08, 09 |
| 11 | `11-estimation.md` | User/AI-assisted dimensions, quantities, wastage, costs, rates | 01, 02, 05, 08, 09 |
| 12 | `12-pdf-report.md` | Report content, layout, generation, download | 01, 02, 06, 07, 09, 10, 11 |
| 13 | `13-testing-and-delivery.md` | Test set, acceptance checklists, README and documentation outline, demo checklist | all |

Each spec defines its own inputs, outputs, validations, error handling and acceptance criteria. No spec may redefine something owned by another file (see section 6).

## 4. Implementation order and milestones

Specs for a flow are written immediately before that flow is implemented.

| Milestone | Specs | Done means |
|-----------|-------|-----------|
| M0 Spike | 05 (draft) | Detection and image generation work from scratch scripts on 6+ real photos; prompts chosen |
| M1 Upload to review | 01-07, then 09 catalogue compatibility foundation, then 08 | Create project, upload, detect, derive support from catalogue compatibility, overlay, correct, save |
| M2 Select to redesign | 09 remaining catalogue/selection work, then 10 | Pick materials per component, variants, generate, compare, regenerate |
| M3 Numbers | 11 | Dimensions (user or AI-assisted), quantities, wastage, costs, editable rates |
| M4 Output | 12 | Downloadable PDF with limitations |
| M5 Hardening | 13 | Tested on sample photos, README, demo recording |

**Checkpoint rule:** if M2 is not working end to end by hour 16 of the 48-hour window, stop other work and fix the upload-to-redesign path first.

**Phased dependency rule for 08 and 09:** the read-only catalogue data and component-type compatibility lookup owned by 09 are implemented first as a small foundation, independent of component editing. Spec 08 consumes that in-process compatibility lookup for `supported` values and component-type changes; it does not call selection or measurement HTTP endpoints. The remaining 09 selection and variant work follows 08 and consumes its component contract. This is a staged dependency, not a circular runtime dependency.

## 5. Glossary (canonical terms)

| Term | Meaning |
|------|---------|
| **Project** | One renovation planning session. Identified by `project_id`. The ID in the URL is the session; there are no user accounts. |
| **Photo** (a.k.a. view) | An uploaded exterior image belonging to a project. The prototype allows one photo per project; the schema supports up to three. |
| **Component** | A detected or user-added region of the photo with a `type`, a label and a normalized box. The working set the user edits. |
| **Detected component** | A normalized, valid component record from one usable AI detection run. Kept for debugging; never edited. The original model response is not persisted. |
| **Locked component** | A component the user created or edited. Re-detection never overwrites it. |
| **Supported component** | A component whose type has at least one compatible material in the catalogue. Only supported components can receive selections. Derived at read time, never stored. |
| **Catalogue** | Read-only structured data: materials, their attributes, default rates and component-type compatibility. |
| **Variant** | A named design: a set of selections (component to material). A project has one or more variants and one active variant. |
| **Selection** | One chosen material for one component within one variant. |
| **Generation** | One redesigned image produced by the image model for a variant. Immutable once created, except for the approval flag. |
| **Stale generation** | A generation whose inputs no longer match the current photo, components and selections of its variant. Computed at read time. |
| **Measurement** | User-provided or AI-estimated dimensions/area for one component. Source is always recorded. |
| **Rate override** | A per-project change to a material's rates or wastage percentage. |
| **Estimate** | Computed (never stored) quantities and costs for a variant. |
| **Report** | A generated PDF file for a variant. |
| **Stage run** | A logged record of one AI or report operation, for debugging. |

## 6. Rules and precedence

1. **Ownership.** `01` owns the data model. `02` owns endpoint shapes and the error format. `04` owns how errors are raised, config is loaded and files are stored. `05` owns everything specific to the AI providers. Feature specs own their business logic.
2. **Conflict rule.** If two specs disagree, `01` wins on data, `02` wins on API shape, and this file wins on scope.
3. **Original-image rule.** All area and measurement logic uses the original photo regions and user-supplied values. A generated image is never measured.
4. **Deterministic-cost rule.** Quantities and costs are computed by Python functions from catalogue data, measurements and rates. An LLM never produces a number that enters a cost calculation. AI-assisted dimension estimates are inputs the user can see and edit, labelled with their source.
5. **User-edit rule.** AI output never overwrites a locked component or a user-entered measurement.
6. **No unlabelled approximations.** Anything AI-estimated or assumption-based is visibly labelled as approximate in the UI and in the report.
7. **Config rule.** Model names, keys, limits, paths and timeouts come from configuration, never from code.
8. **Scope rule.** Anything not listed here is out of scope. Additions need an explicit entry in the scope table below with a reason.

## 7. Scope

**Mandatory:** upload with quality rejection and guidance; component detection; region review, correction, add and remove; catalogue-driven material selection per component; multiple design variants with switching; redesign with original/redesigned comparison and regenerate; user-provided dimensions with optional AI-assisted approximate estimates; quantities, wastage, material and labour cost, category totals, grand total; editable rates with recalculation; PDF report including assumptions and limitations; saved and reopenable projects.

**Simplified for the prototype:**

| Item | Simplification |
|------|---------------|
| Photos | One photo per project; schema and limit setting allow up to three |
| Variants | Create, duplicate, rename, switch, delete; no side-by-side comparison grid |
| Users | No accounts; unguessable project ID in the URL is the session |
| Area estimation | User-supplied approximate dimensions or areas first; optional Gemini-assisted estimates; no pixel-to-real-world geometry reconstruction |
| Region editing | Draw, move-by-redraw, retype, delete; no resize handles |
| Material guidance | Short static maintenance and durability notes stored in the catalogue; no AI advice |
| Report | Clear tables and images; no styling polish |
| Progress feedback | Synchronous requests with a busy indicator; no job queue |

**Postponed:** multi-photo fusion, authentication, automated render verification, segmentation/depth/3D, AI material recommendations, region resize handles, side-by-side variant comparison, rate limiting.

## 8. Traceability to the assessment PDF

Status: **M** mandatory, **S** simplified, **P** postponed. "Spec" lists the file(s) that implement the requirement.

### Section 1 - Overview

| PDF requirement | Status | Spec |
|-----------------|--------|------|
| 1. Accept exterior images of a residential building | M | 06 |
| 2. Generate redesigned visual options using selected materials | M | 09, 10 |
| 3. Estimate material quantities required | M | 11 |
| 4. Calculate a detailed, transparent renovation cost | M | 11, 12 |
| Help the homeowner decide before construction | M | whole system, 12 |

### Section 2 - Core problem

| PDF requirement | Status | Spec |
|-----------------|--------|------|
| A. Visualization gap: see the actual house redesigned | M | 10 |
| B. Material confusion: which material, where applied | M | 08 (component mapping), 09 (compatibility) |
| B. Maintenance and durability differences | S | 09 (static notes in catalogue shown in UI), 12 (in report) |
| C. Cost uncertainty: approximate areas, arbitrary wastage, unclear labour | M | 11 (explicit wastage, labour rates, uncertainty labelling) |
| Reduce dependency on manual estimation, structured calculation | M | 11 |

### Section 3 - Goals

| PDF requirement | Status | Spec |
|-----------------|--------|------|
| 1. Upload a photo of the house exterior | M | 06 |
| 2. Select design preferences and materials | M | 09 |
| 3. View a realistic redesigned version of their own house | M | 10 |
| 4. Obtain material quantity estimates | M | 11 |
| 5. Receive a detailed cost breakdown | M | 11, 12 |
| Function as a pre-construction planning assistant | M | whole system |

### Section 4 - Target users

| PDF requirement | Status | Spec |
|-----------------|--------|------|
| Primary: homeowners, new house owners | M | 03 (non-technical UI), 13 |
| Secondary: contractors, architects, builders, consultants, suppliers | S | 12 (report usable as discussion document); no role-specific features |

### Section 5 - Functional requirements

| PDF requirement | Status | Spec |
|-----------------|--------|------|
| 5.1 Upload exterior images | M | 06 |
| 5.1 Extract clear usable views | S | 06, 07 (single photo; quality flag; guidance to retake) |
| 5.1 Reject extremely low-quality input | M | 06 (technical checks), 07 (AI quality flag) |
| 5.1 Guide the user if the image is unusable | M | 06, 07, 03 |
| 5.2 Identify walls, windows, balconies, pillars, parapets, gates, roof edges | M | 07 |
| 5.2 Mapped representation of building surface | S | 07, 08 (normalized boxes, not masks) |
| 5.2 User can review detected regions | M | 08 |
| 5.2 User can adjust or correct areas | M | 08 |
| 5.3 Material catalogue | M | 09 |
| 5.3 Different materials on different sections | M | 09 |
| 5.3 Preview multiple combinations, switch designs | S | 09 (variants), 10 (one generation per variant at a time) |
| 5.4 Output shows the user's actual house redesigned | M | 10 |
| 5.4 Preserve original structure | S | 10 (prompt-based preservation; human review as verification) |
| 5.4 Realistically apply textures/colours/materials | M | 10 |
| 5.4 Compare original and redesigned | M | 10, 03 |
| 5.5 Approximate area of each building surface | S | 11 (user-supplied first, AI-assisted optional, all editable) |
| 5.5 Walls, balconies, pillars, railing length, cladding area | M | 11 |
| 5.5 Reference assumptions, perspective, user input | S | 11 (user input and assumptions; perspective estimation not required) |
| 5.6 Required material quantity | M | 11 |
| 5.6 Approximate wastage | M | 11 |
| 5.6 Required coverage (e.g. paint) | M | 09 (coverage data), 11 |
| 5.6 Example outputs: paint area, tiles, cladding, railing length | M | 11 |
| 5.7 Material cost, labour cost, category total, grand total | M | 11 |
| 5.7 Modify material rates, recalculated costs | M | 11 |
| 5.8 Downloadable report: original, redesign, materials, quantities, costs | M | 12 |
| 5.8 Usable as a discussion document with contractors | M | 12 |

### Section 6 - Non-functional requirements

| PDF requirement | Status | Spec |
|-----------------|--------|------|
| Usable by non-technical users | M | 03, 13 |
| Works on standard internet connections | M | 03 (small payloads), 05 (image downscaling before AI calls) |
| Results within a reasonable time | M | 05 (timeouts), 03 (busy indicator with elapsed time) |
| Allow re-editing and saving projects | M | 01, 04, 06 |
| Handle multiple users simultaneously | S | 04 (per-request DB connections, WAL mode, no shared in-memory state; project isolation by ID) |

### Section 7 - Assumptions

| PDF assumption | Handling | Spec |
|----------------|----------|------|
| Residential, low-rise building | Stated in UI guidance and report limitations | 03, 12 |
| Exterior renovation only | Catalogue and vocabulary cover exterior components only | 07, 09 |
| No interior design | Out of scope | this file |
| No structural engineering calculations | Stated in report limitations | 12 |
| Estimates are advisory, not binding | Disclaimer on estimate screen and in report | 11, 12 |

### Section 8 - Constraints

| PDF constraint | Handling | Spec |
|----------------|----------|------|
| No professional drawings required | Only a photo and approximate user numbers | 06, 11 |
| No specialized measuring equipment | User estimates in feet; optional AI-assisted estimates | 11 |
| Rely primarily on visual media input | Photo is the primary input; user numbers refine it | 06, 07, 11 |

### Section 9 - Deliverables

| PDF deliverable | Status | Spec |
|-----------------|--------|------|
| System architecture | M | this file, 01, 02, 04 |
| User workflow | M | this file (section 9), 03 |
| Prototype: image upload | M | 06 |
| Prototype: material application | M | 09 |
| Prototype: redesigned output | M | 10 |
| Prototype: area estimation | M | 11 |
| Prototype: cost estimation | M | 11 |
| Documentation: how the estimation works | M | 11 (source of truth), 13 (README section) |
| Documentation: limitations | M | 11, 12, 13 |

## 9. User workflow (canonical)

| Workflow step | Screen (see 03) | Primary spec |
|---------------|-----------------|--------------|
| 1. Create project, upload photo | Upload | 06 |
| 2. Detect components | Components | 07 |
| 3. Review, correct, add, remove regions | Components | 08 |
| 4. Load compatible materials | Materials | 09 |
| 5. Select materials per component | Materials | 09 |
| 6. Generate redesign | Redesign | 10 |
| 7. Compare original and redesign, regenerate | Redesign | 10 |
| 8. Provide dimensions (or AI-assisted estimate) | Estimate | 11 |
| 9. Quantities, wastage, costs, edit rates | Estimate | 11 |
| 10. Generate and download PDF | Report | 12 |
| 11. Save and revisit projects | Project list | 06 |

## 10. Acceptance criteria for the specification set

- Every field name, endpoint, enum value and file path used in any spec appears in `01` or `02`.
- Every PDF requirement in section 8 above points to at least one implementing spec.
- No spec contains application code; short illustrative JSON and path layouts are allowed.
