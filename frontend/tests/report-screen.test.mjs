import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../static/js/screens/report.js", import.meta.url),
  "utf8"
);
const { reportScreen } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

test("redesign selector distinguishes approved, unapproved, and outdated images", () => {
  reportScreen.ctx = { ui: { formatDate: () => "6 Nov 2026" } };
  assert.equal(
    reportScreen.generationLabel({ created_at: "2026-11-06", is_approved: true, is_stale: false }),
    "Approved - 6 Nov 2026"
  );
  assert.equal(
    reportScreen.generationLabel({ created_at: "2026-11-06", is_approved: false, is_stale: false }),
    "Not approved - 6 Nov 2026"
  );
  assert.equal(
    reportScreen.generationLabel({ created_at: "2026-11-06", is_approved: true, is_stale: true }),
    "Outdated - 6 Nov 2026"
  );
});

test("report screen renders readiness and previous report links", async () => {
  const state = {
    project: { active_variant_id: "var_one" },
    activeVariantId: "var_one",
    photos: [{ id: "pho_one" }],
    variants: [{ id: "var_one", name: "Design 1", selections: [{ material_id: "paint", component_id: "cmp_one" }] }],
    generations: [],
    estimate: { missing_measurements: [] },
    measurements: [{ component_id: "cmp_one", source: "user" }],
    rates: [{ material_id: "paint", is_overridden: false }],
    reports: [{ id: "rep_old", variant_id: "var_one", grand_total: 100, currency: "INR", created_at: "2026-11-06" }],
  };
  const container = {
    innerHTML: "",
    querySelector: () => ({ addEventListener() {} }),
  };
  reportScreen.container = container;
  reportScreen.loading = false;
  reportScreen.loadError = null;
  reportScreen.busy = false;
  reportScreen.selectedGenerationId = null;
  reportScreen.ctx = {
    projectId: "prj_one",
    store: { getState: (key) => state[key] },
    ui: {
      escapeHtml: (value) => String(value),
      formatDate: () => "6 Nov 2026",
      formatCurrency: () => "INR 100.00",
    },
    api: { getReportDownloadUrl: () => "/download" },
    router: { navigate() {} },
  };
  await reportScreen.render();
  assert.match(container.innerHTML, /Readiness/);
  assert.match(container.innerHTML, /Default placeholder rates are used/);
  assert.match(container.innerHTML, /Generate PDF report/);
  assert.match(container.innerHTML, /Deleted design|Design 1/);
  assert.match(container.innerHTML, /href="\/download"/);
});
