import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../static/js/stepper.js", import.meta.url),
  "utf8"
);
const { renderStepper } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

function renderWith({ photos = [], componentCount = 0 } = {}) {
  const container = {
    innerHTML: "",
    querySelectorAll: () => [],
  };
  const state = {
    project: { photo_count: photos.length, component_count: componentCount },
    photos,
    components: [],
    variants: [],
    activeVariantId: null,
    generations: [],
    measurements: [],
    reports: [],
  };
  renderStepper(container, "upload", "prj_test", {
    getState: (key) => state[key],
  });
  return container.innerHTML;
}

test("usable successful detection completes Components with no regions", () => {
  const html = renderWith({
    photos: [{ quality_usable: true, detected_at: "2026-11-07T00:00:00Z" }],
  });
  assert.match(html, /class="step-item step-item--done" data-step="components"/);
  assert.match(html, /<span class="step-bubble">✓<\/span>/);
});

test("component count alone does not complete Components", () => {
  const html = renderWith({ componentCount: 2 });
  assert.match(html, /class="step-item step-item--available" data-step="components"/);
});

test("unusable or undetected photos do not complete Components", () => {
  for (const photo of [
    { quality_usable: false, detected_at: "2026-11-07T00:00:00Z" },
    { quality_usable: true, detected_at: null },
  ]) {
    const html = renderWith({ photos: [photo] });
    assert.match(html, /class="step-item step-item--available" data-step="components"/);
  }
});
