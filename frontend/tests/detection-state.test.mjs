import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../static/js/detection-state.js", import.meta.url),
  "utf8"
);
const { getDetectionViewState } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

test("usable detection with zero components has its own success state", () => {
  assert.equal(
    getDetectionViewState(
      { quality_usable: true, detected_at: "2026-11-07T00:00:00Z" },
      []
    ),
    "empty"
  );
});

test("detection state distinguishes ready, unusable, and not-yet-detected photos", () => {
  assert.equal(
    getDetectionViewState(
      { quality_usable: true, detected_at: "2026-11-07T00:00:00Z" },
      [{ id: "cmp_test" }]
    ),
    "ready"
  );
  assert.equal(
    getDetectionViewState(
      { quality_usable: false, detected_at: "2026-11-07T00:00:00Z" },
      []
    ),
    "unusable"
  );
  assert.equal(getDetectionViewState({ detected_at: null }, []), "not-detected");
});

test("detection failures and manual review are explicit screen states", () => {
  assert.equal(
    getDetectionViewState(
      { quality_usable: true, detected_at: "2026-11-07T00:00:00Z" },
      [],
      new Error("provider unavailable")
    ),
    "failed"
  );
  assert.equal(getDetectionViewState(null, [], null, true), "manual");
  assert.equal(getDetectionViewState(null, []), "no-photo");
});
