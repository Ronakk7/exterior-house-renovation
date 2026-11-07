# 13 - Testing and Delivery

**Purpose:** record the implemented test strategy, verified acceptance evidence, delivery documentation, remaining manual acceptance work and deployment requirements for the completed MVP.
**Depends on:** specifications `00` to `12` and supplemental UX specification `14`.
**Enables:** final hand-off after the remaining manual evaluation and deployment prerequisites are completed.

**Status (2026-11-07):** implementation and automated verification are complete for the documented MVP. This is not a declaration that real-house acceptance testing, assessment/demo preparation, or deployment is complete. Verified results and open items are recorded in sections 7 and 11.

---

## 1. Principles

1. **Test the contract, not the model.** Automated tests use mocked AI (`05` section 9) so they are repeatable and do not spend API credits. Real model integration smoke checks are recorded separately from real-house acceptance.
2. **Every spec's acceptance criteria are executable.** Each spec's "Acceptance criteria" and "Automated test cases" sections are the test list. This file adds the cross-spec flow tests and the manual script.
3. **Prove the money.** `cost_service` has exact-value unit tests (`11` section 6) and runs with no database.
4. **Keep a working demo at all times.** From M2 onward, the full flow must run in mock mode so the demo never depends on the network.
5. **Test what the user would do wrong.** Bad files, double clicks, back-navigation, edits after generation.

## 2. Automated test strategy

### 2.1 Tooling

| Need | Choice |
|------|--------|
| Backend test runner | Python standard-library `unittest` |
| API tests | FastAPI/Starlette test client; no live server required |
| Frontend test runner | Node.js built-in `node:test` |
| Test images | Generated in test code using Pillow, including photo/rendering fixtures, undersized, large, EXIF-rotated and malformed inputs |
| PDF checks | Assertions against generated reports in the existing unittest suite |
| AI | Mock clients and `AI_MOCK_SCENARIO`; live calls are separate smoke tests |

Do not migrate the project to pytest or add a frontend build system. Runtime dependencies are pinned in `backend/requirements.txt`; clean-install results are recorded in section 7.1. There is no separate `requirements-dev.txt` or npm package manifest.

### 2.2 Test isolation

Tests create isolated temporary database and storage locations and use a fresh application instance/test client. Per-test project, photo, component, selection, measurement, and report data are created as needed. Mock providers/scenarios cover deterministic success and failure paths without live model requests. Tests do not share database or storage state.

### 2.3 Current test layout

The feature-oriented suites are located in `backend/tests/` and `frontend/tests/`; they do not use the former illustrative `unit/api/flow` layout. Representative files include:

```
backend/tests/
  test_ai_integration.py
  test_api_endpoints.py
  test_catalogue_variants.py
  test_components.py
  test_detection.py
  test_estimation.py
  test_foundation.py
  test_redesign.py
  test_reports.py
  test_uploads.py
frontend/tests/
  detection-state.test.mjs
  materials-screen.test.mjs
  report-screen.test.mjs
  stepper.test.mjs
  upload-api.test.mjs
```

The exact test-file set may grow as features are added. Use the commands in section 7.1 to run the complete suites.

## 3. Cross-spec flow tests

### 3.1 Full happy path (mock mode)

| # | Step | Assertions |
|---|------|-----------|
| 1 | Create project | `Design 1` exists and is active |
| 2 | Upload 1600x1200 JPEG | 201; photo row; file on disk |
| 3 | Detect | 200, `usable` true, about 10 components, all boxes valid, `supported` true for walls and false for windows |
| 4 | Edit one component's type; add one component; delete one | Edited and added are locked; counts as expected |
| 5 | Detect again | Locked components unchanged; others replaced; `kept_locked_count` correct |
| 6 | Select materials: wall, pillar, railing | 200 each; incompatible attempt returns 422 |
| 7 | Generate redesign | 201; image file; aspect equals original; not stale |
| 8 | Change one selection | The generation reports `is_stale` true |
| 9 | Generate again and approve | One approved generation; previous not approved |
| 10 | Enter measurements for the three components | 200 each; `net_area_sqft` correct |
| 11 | `GET estimate` | Totals equal hand-computed values for the fixture |
| 12 | Change a rate | Estimate changes; `is_stale` unchanged |
| 13 | Create report | 201; PDF parses; contains grand total; row in `reports` |
| 14 | Reload project data | Everything is still present (persistence) |
| 15 | Delete project | No rows, no files |

### 3.2 Second variant flow

Create a second design by duplicating `Design 1`; change one material; generate for it; verify estimates differ and generations belong to the right variants; switch the active variant; delete the second; verify files removed and the first design intact.

### 3.3 Concurrency flow

Two projects used in parallel threads for upload, detect and generate: no cross-contamination, no database lock errors. Two simultaneous generations in one project: exactly one succeeds, the other returns `GENERATION_IN_PROGRESS`.

### 3.4 Supplemental material customization UX (Spec 14)

The delivered frontend and backend coverage includes:

- Clicking an image region and choosing a region-list entry keep the selected component and customization panel synchronized.
- Material cards display catalogue previews/details and immediately save selections using the existing API.
- Paint and texture selections support preset swatches and validated custom HEX colours; other categories do not expose colour editing.
- Selected state, save feedback and confirmed bulk material application are covered.
- Redesign preferences apply only to explicitly selected regions. The prompt version is `rd-v2`; the existing input fingerprint, complete keep-set and stale-generation checks remain in force.

The 2026-11-07 browser smoke check verified saved material and preset-colour behavior with a synthetic house image and confirmed the mobile stacked layout. It did not constitute acceptance testing with a real house image or architectural rendering.

## 4. Test image set (for manual M0 and M5 checks)

Use authorized exterior photographs and at least one clear 3D architectural rendering; keep user/source images outside the repository (or include only appropriately licensed test assets).

| # | Image | Purpose |
|---|-------|---------|
| 1 | Two-storey house, front, daylight, clear photograph | Baseline |
| 2 | Single-storey bungalow with gate | Gate and parapet |
| 3 | House with balcony and glass or metal railing | Railing and balcony |
| 4 | House with pillars and a porch | Pillars |
| 5 | House at a slight angle | Box accuracy under perspective |
| 6 | Dusk or shadowy photo | Lighting robustness |
| 7 | House partly hidden by trees or a vehicle | Obstruction handling |
| 8 | Clear 3D architectural exterior rendering / CGI visualization | Must be accepted; visible components detected |
| 9 | Not a house (e.g. interior or a landscape) | `usable: false` path |
| 10 | Floor plan or unrelated drawing | `usable: false` path |
| 11 (optional) | Small apartment block | Assumption boundary |
| 12 (optional) | Very low-resolution phone image | Upload and quality guidance |

For each image, record its source/type, detection quality, redesign structure and observed latency in the acceptance record (section 7.5). Verify that renderings are not rejected solely for being computer-generated.

## 5. Failure scenario matrix

This matrix describes expected behavior and regression targets; it is not a claim that every row has a dedicated automated test. The verified suite totals and specific manual gaps are in section 7.

| Area | Scenario | Expected result |
|------|----------|-----------------|
| Upload | Wrong type, corrupt, too large, too small, second photo | `415`, `422`, `413`, `422`, `409` with messages from `06` |
| Upload | Rotated EXIF photo | Upright dimensions; browser display upright (manual) |
| Detection | `unusable` scenario | `200`, `usable: false`, components unchanged |
| Detection | `invalid_json` | `502 AI_INVALID_RESPONSE`; components unchanged; stage run `failed` |
| Detection | `blocked`, `timeout`, `rate_limited` | `422`, `504`, `429` with mapped messages |
| Detection | Not configured (no key, mock off) | `503 AI_NOT_CONFIGURED` |
| Detection | Re-run with edited components | Locked kept; unlocked replaced |
| Detection | Two simultaneous requests | Second `409 CONFLICT` |
| Components | Invalid box, invalid type, 61st component | `422`, `422`, `409` |
| Components | Type change removing selections | Selections removed; warning |
| Selection | Incompatible material, colour on stone, unknown param | `422` each |
| Variants | Duplicate name, 11th variant, last variant delete | `409` each |
| Redesign | No selections, no photo, >12 groups | `409`, `409`, `422` |
| Redesign | `blocked`, `timeout` | Failed generation stored; error with `generation_id` |
| Redesign | Aspect too different | `AI_INVALID_RESPONSE`; failed generation |
| Redesign | Restart mid-generation | `failed` with `INTERRUPTED` |
| Estimate | Missing measurement | Listed, excluded, disclaimer |
| Estimate | Wrong mode or unsupported component | `422` |
| Estimate | AI estimate timeout | `504`; no measurements; manual entry still possible |
| Rates | Negative rate, wastage 60 | `422` |
| Report | No selections, failed generation chosen, render error | `409`, `409`, `500` without leftovers |
| Report | Non-Latin label | No crash; replaced |
| System | Invalid ID formats in paths | `404` |
| System | Unexpected exception | `500 INTERNAL_ERROR`, no internals, request ID present |
| System | Path traversal attempt | Rejected |
| System | Key never appears in logs or responses | Verified by search in a test |

## 6. Manual end-to-end script (about 15 minutes, real AI)

Run with a real key after M2 and again at M5.

1. Open the site. Create a project "Test house".
2. Upload image 1. Confirm the preview, size and guidance.
3. Go to Components. Click **Detect components**. Wait. Check that boxes land on the right parts of the house.
4. Fix at least three things: change a type, delete a wrong box, add a missing pillar with the drawing tool, redraw one box.
5. Click **Detect again** and confirm that your edits stay.
6. Go to Materials. Click an image region and confirm the same region is selected in the region list and customization panel. Pick a wall texture and preset or valid HEX colour, a stone for a pillar, and a glass railing; confirm colour controls are absent for non-paint/texture materials. Use the confirmed bulk-apply action for pillars and verify saved feedback.
7. Create a second design "Design 2" by duplicating and change the wall.
8. Go to Redesign. Generate for Design 1. Compare with the slider. Check geometry: window count, balcony, pillars. Approve it.
9. Change a material; confirm the image is marked Outdated. Generate again and verify `rd-v2` applies preferences only to explicitly selected regions.
10. Go to Estimate. Enter dimensions for each selected region; try **Estimate with AI** for the others; edit one AI value and confirm the badge changes.
11. Change a rate and the wastage of one material; watch totals update.
12. Go to Report. Check the readiness list; generate the PDF; open it and verify every section.
13. Reload the browser; open the project from the list; confirm everything is there.
14. Try bad inputs: a GIF, a 15 MB file, a text file renamed `.jpg`, a negative width.
15. Turn off the network briefly and press Generate: a readable error appears and nothing breaks.

## 7. Verification and acceptance status

### 7.1 Automated tests and clean dependency install

Latest recorded clean-environment verification (2026-11-07):

| Check | Result |
|-------|--------|
| Backend `unittest` suite | **98 passed** |
| Frontend Node.js `node:test` suite | **22 passed** |
| Full mock upload-to-report workflow | Passed, including PDF creation and download |
| JavaScript syntax checks | **15/15 modules passed** |
| Clean virtual environment install from `backend/requirements.txt` | Completed |
| `pip check` | No broken requirements |
| Verified key package versions | Pydantic 2.12.5; google-genai 3.0.0; httpx 0.28.1 |

Commands from the repository root:

```powershell
python -m unittest discover -s backend\tests
node --test frontend\tests
```

### 7.2 AI integration evidence

One minimal live API smoke test per configured integration succeeded in the prior verification: Gemini Vision and Nano Banana. A further single live Gemini Vision check on a clear 3D architectural exterior rendering from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Contemporary_Residence_with_Gable_Windows_%E2%80%93_3D_Architectural_Visualization.jpg) (Tuantranseo, CC BY 4.0) returned HTTP 200, `usable: true`, and 12 components with prompt version `det-v2`. The temporary test copy was removed and is not included in the repository. Automated and full-workflow tests use mocks. These smoke checks verify basic request/response handling only; they do not establish model quality across a representative image set or guarantee geometry preservation.

### 7.3 UX/browser evidence

A browser smoke check using a synthetic house image verified the Materials screen's saved material selection, colour preset behavior and mobile stacked layout. Rendering regression tests use mock Vision responses and verify that both a photo fixture and a rendered-exterior fixture pass through detection, material selection, measurement and estimate; interior/floor-plan/blurry-image responses remain unusable. Spec 14's frontend tests cover synchronized image/list selection, customization cards, category-specific colour controls, HEX validation, bulk apply/save feedback, and `rd-v2` prompt handling. Live Vision accepted one actual 3D exterior rendering, but manual end-to-end acceptance with real photographs and renderings remains outstanding.

### 7.4 Implementation checklist

- [x] Project, upload, detection, region editing, catalogue, variants and material selection implemented and covered by automated tests.
- [x] Spec 14 component selection synchronization, material customization, paint/texture colour presets and HEX input, bulk application, and `rd-v2` preference scope implemented.
- [x] Redesign, measurement, deterministic estimate and PDF report flow covered by the mock integration workflow.
- [x] README and Mermaid architecture documentation are present and describe the current architecture and deployment constraints.
- [ ] Complete the manual end-to-end script using representative exterior photographs and a 3D rendering; record observations.
- [ ] Select a deployment target, configure persistent database/storage, trusted production origins and access protection; no deployment has been performed.
- [ ] Prepare/rehearse assessment demo assets if required; sample-photo set, video and demo rehearsal are not verified as complete.

### 7.5 Photograph/rendering acceptance record

The previous live smoke checks were API-level and no representative photograph/rendering acceptance run or per-image result record is available. Do not infer detection accuracy, redesign structure preservation, or latency targets from the API smoke checks.

| Photo set | Detection quality | Redesign structure | Latency | Status |
|-----------|-------------------|--------------------|---------|--------|
| Authorized photograph and rendering set | Not recorded | Not recorded | Not recorded | Manual acceptance outstanding |

### 7.6 Running and recording acceptance tests

For manual acceptance, use the script in section 6 with authorized exterior photographs and at least one actual 3D architectural rendering. Record whether each image is deemed usable, box quality, redraw/edit preservation after re-detection, selected-region redesign behavior, generation staleness after material changes, report content, and observed latency. For rendering-based AI measurements, record whether estimates were checked against a known scale or on site. Do not include private images or API credentials in the repository or reports.

## 8. Performance and reliability targets (not benchmarked)

The following are design targets, not measured acceptance results. The recorded verification does not include a performance benchmark or a five-user load test.

| Action | Target (typical) | Hard limit |
|--------|------------------|------------|
| Upload and validation of a 5 MB photo | under 2 s | 10 s |
| Detection (real model) | under 30 s | 60 s (timeout) |
| Redesign (real model) | under 90 s | 120 s (timeout) |
| Estimate calculation (`GET estimate`) | under 200 ms | 1 s |
| Region edit, selection or rate write | under 200 ms | 1 s |
| PDF generation | under 5 s | 15 s |
| Concurrent users | 5 users using different projects without errors | n/a |

Timeouts are from `04` section 4.1 and `05` section 6.

## 9. Delivery documentation status

The root `README.md` contains Windows setup and run instructions, environment configuration, test commands, end-to-end usage, AI responsibilities, deterministic estimation methodology, privacy/limitations, safe clean-database guidance, packaging exclusions, and deployment requirements. `docs/architecture.md` contains high-level and end-to-end Mermaid diagrams. These documents describe the single FastAPI application, SQLite and local storage, Gemini Vision, Nano Banana, Python costing, and ReportLab.

Documentation is present and consistent with the implemented stack. This does not mean a deployment, demo rehearsal, sample asset package, or production access-control setup has been completed.

## 9.1 Assessment documentation deliverables (`00` section 8, PDF section 9)

| Deliverable | Where it lives |
|-------------|----------------|
| System architecture | `docs/architecture.md`, linked from README |
| User workflow | README end-to-end use section |
| How the estimation works | README estimation methodology section |
| Limitations and deployment requirements | README data/privacy/limitations and deployment sections |
| Working prototype | Repository; local startup documented, deployment not performed |

## 10. Demo plan

### 10.1 Demo flow (about 6 minutes)

1. Problem in one sentence, then create a project.
2. Upload a prepared house photo (photo 1 or 3).
3. Detect; show the boxes; correct one thing live; mention locked edits.
4. Materials: choose wall texture, pillar stone, glass railing; duplicate to a second design.
5. Generate the redesign; use the comparison slider; approve it.
6. Estimate: enter dimensions; show an AI estimate with its label; change a rate; watch totals update; point at ranges and disclaimers.
7. Generate the PDF and open it.
8. Close with limitations and what would be next.

### 10.2 Fallbacks

| Risk | Mitigation |
|------|------------|
| Network or provider fails | Switch to mock mode (`AI_MOCK_MODE=true`) and continue; say so |
| Real model result looks poor | Use pre-generated sample outputs kept under `samples/` and a recorded screen capture of a full real run |
| Detection misses components | Draw them manually (a designed feature) |
| Slow generation | Start the generation first, explain the app while it runs |
| Machine problem | Recorded video of the complete flow |

### 10.3 Assets to prepare

- 2 prepared house photos and their saved results (original, redesign, PDF).
- A 5 to 8 minute screen recording of the full flow with real AI.
- A short clean database snapshot with one completed project that can be opened instantly.

## 11. Submission and deployment checklist

- [x] Automated backend and frontend suites pass in mock mode (section 7.1).
- [x] Dependency installation in a clean virtual environment and `pip check` completed (section 7.1).
- [x] README and architecture diagrams are present.
- [x] Packaging guidance excludes secrets, virtual environments, caches, temporary output, runtime database and storage; existing local data is to be preserved.
- [ ] Complete the representative real-photo acceptance script and record results.
- [ ] Perform a fresh-clone timing/acceptance check; no under-10-minute result is recorded.
- [ ] Select a deployment target and verify its host/port binding.
- [ ] Provision persistent storage for SQLite and `STORAGE_ROOT`, configure production settings and explicit trusted CORS origins.
- [ ] Configure access protection before any shared/public deployment; the app has no built-in authentication. Do not expose a paid Gemini key on an unrestricted instance.
- [ ] Complete any required demo rehearsal and prepare authorized sample assets.

No deployment has been performed. CORS is not an authorization mechanism. SQLite database files (including WAL-related runtime state) and project storage must persist together across restarts/deployments.

## 12. Known limitations and remaining acceptance work

- Manual testing with a representative set of real house photographs and 3D renderings, including detection quality and redesign geometry review, is not recorded.
- Model smoke checks are basic integration checks only; image quality, preservation, and performance targets have not been comprehensively evaluated.
- The application has no accounts or project-level authorization. Projects are shared within an instance; use access controls for any shared assessment/demo environment.
- Starter catalogue prices and coverage are placeholders and must be replaced with suitable regional values before treating estimates as quotations.
- One exterior image per project is the default; photographs and clear renderings are accepted, but rendering-derived measurements are not verified physical dimensions. Regions are rectangular rather than segmentation masks, and perspective/3D reconstruction is not provided.
- Redesign structure preservation is prompt-based and requires human review. Re-detection may replace unlocked components and invalidate related selections or AI measurements; locked user corrections are protected.
- Standard PDF fonts have limited character support; unsupported characters are sanitized.
- Performance/load targets, a fresh-clone time target, deployment, production configuration and demo rehearsal remain unverified.

## 13. Deferred scope

Not included in this delivery: segmentation masks, perspective correction, multi-photo workflows, 3D reconstruction, automated structural verification, user accounts/authorization, rate limiting, and regional catalogue pricing. These are limitations or future work, not pending parts of the completed Specs 00–14 implementation.

## 14. Completion status

- Automated mock-mode verification and clean dependency checks are recorded as passed.
- Spec 14 material customization UX and `rd-v2` handling are implemented and covered by focused tests.
- Minimal live smoke checks for both Gemini integrations succeeded previously; no new live tests were run for this documentation update.
- Real-photo acceptance, performance/load benchmarking, deployment, access-control setup and demo rehearsal are not complete or evidenced.
- This specification records implementation and verification status; it does not certify production readiness or deployment completion.
