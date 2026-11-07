import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../static/js/screens/materials.js", import.meta.url),
  "utf8"
);
const executable = source
  .replace(
    'import { ImageStage } from "../imagestage.js";',
    `const ImageStage = class {
      constructor() {
        this.overlayEl = {
          boxes: [],
          querySelectorAll() { return this.boxes; },
        };
      }
      renderBoxes(components) {
        this.overlayEl.boxes = components.map((component) => ({
          style: {},
          getAttribute: (name) => name === "data-id" ? component.id : null,
          classes: new Set(),
          classList: {
            toggle(name, enabled) {
              if (enabled) this.owner.classes.add(name);
              else this.owner.classes.delete(name);
            },
            owner: null,
          },
        })).map((box) => {
          box.classList.owner = box;
          return box;
        });
      }
      onBoxClick(callback) { this.boxClick = callback; }
      destroy() {}
    };`
  )
  .replace(
    'import { renderStepper } from "../stepper.js";',
    "const renderStepper = () => {};"
  );
const { MATERIAL_COLOR_PRESETS, getCompatibleMaterials, materialsScreen } = await import(
  `data:text/javascript;base64,${Buffer.from(executable).toString("base64")}`
);

const paint = {
  id: "paint_beige",
  name: "Warm paint",
  category: "paint",
  compatible_types: ["wall"],
  pricing_unit: "sqft",
  swatch_hex: "#E8DCC8",
  prompt_description: "smooth matte warm beige paint",
  maintenance_note: "Repaint periodically.",
  durability_note: "Good.",
};
const stone = {
  id: "stone_slate",
  name: "Slate cladding",
  category: "stone_cladding",
  compatible_types: ["wall"],
  pricing_unit: "sqft",
  swatch_hex: "#6B7B8D",
  prompt_description: "natural grey slate",
  maintenance_note: "Seal periodically.",
  durability_note: "Excellent.",
};
const catalogue = {
  categories: [
    { id: "paint", name: "Paint" },
    { id: "stone_cladding", name: "Stone cladding" },
  ],
  materials: [paint, stone],
};
const escapeHtml = (value) => String(value);

test("image and list region selection use the same local selection path", async () => {
  let listClick;
  const listButton = {
    dataset: { componentId: "cmp_wall" },
    addEventListener: (_event, callback) => { listClick = callback; },
  };
  const screen = Object.create(materialsScreen);
  screen.ctx = {
    store: { getState: (key) => key === "components"
      ? [{ id: "cmp_wall", type: "wall", supported: true }]
      : [] },
    api: {},
  };
  screen.container = {
    querySelector: () => ({}),
    querySelectorAll: (selector) => selector === ".materials-region" ? [listButton] : [],
  };
  const selected = [];
  screen.updateMaterialPanel = async () => selected.push(screen.selectedComponentId);

  screen.mountStage(
    { image_url: "/photo" },
    [{ id: "cmp_wall", type: "wall", supported: true }],
    new Map(),
    new Map()
  );
  await screen.stage.boxClick("cmp_wall");
  screen.selectedComponentId = null;
  screen.bindRegionList();
  await listClick();

  assert.deepEqual(selected, ["cmp_wall", "cmp_wall"]);
});

test("panel identifies the selected region and visibly marks only saved compatible choices", () => {
  const screen = Object.create(materialsScreen);
  screen.ctx = { ui: { escapeHtml }, store: { getState: () => catalogue } };
  screen.categoryFilter = "all";
  screen.renderApplyAll = () => "";
  const compatible = getCompatibleMaterials(catalogue, "wall");
  const html = screen.renderChoicePanel({
    selectedComponent: { id: "cmp_wall", label: "Front wall", type: "wall" },
    selection: { component_id: "cmp_wall", material_id: paint.id, params: {} },
    catalogue,
    compatible,
    categories: ["paint", "stone_cladding"],
    filtered: compatible,
    activeVariant: { selections: [] },
    materialById: new Map(catalogue.materials.map((item) => [item.id, item])),
  });

  assert.match(html, /Front wall/);
  assert.match(html, /wall/);
  assert.match(html, /Current material: <strong>Warm paint<\/strong>/);
  assert.match(html, /material-card--selected/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /<details class="material-card__details">/);
  assert.match(html, /smooth matte warm beige paint/);
  assert.match(html, /Slate cladding/);
});

test("compatibility filtering uses catalogue types and defaults to all compatible materials", () => {
  assert.deepEqual(
    getCompatibleMaterials(catalogue, "wall").map((material) => material.id),
    ["paint_beige", "stone_slate"]
  );
  assert.deepEqual(getCompatibleMaterials(catalogue, "railing"), []);
});

test("paint exposes preset and open HEX controls, while other categories do not", () => {
  const screen = Object.create(materialsScreen);
  screen.ctx = { ui: { escapeHtml }, store: { getState: () => catalogue } };
  screen.categoryFilter = "all";
  screen.renderApplyAll = () => "";
  const args = {
    selectedComponent: { id: "cmp_wall", label: "Front wall", type: "wall" },
    catalogue,
    compatible: [paint, stone],
    categories: ["paint", "stone_cladding"],
    filtered: [paint, stone],
    activeVariant: { selections: [] },
    materialById: new Map(catalogue.materials.map((item) => [item.id, item])),
  };
  const paintHtml = screen.renderChoicePanel({
    ...args,
    selection: { component_id: "cmp_wall", material_id: paint.id, params: {} },
  });
  const stoneHtml = screen.renderChoicePanel({
    ...args,
    selection: { component_id: "cmp_wall", material_id: stone.id, params: {} },
  });

  assert.match(paintHtml, /material-color-presets/);
  assert.match(paintHtml, /selection-color-picker/);
  assert.match(paintHtml, /selection-color-hex/);
  assert.match(paintHtml, /Using the material's default colour/);
  assert.match(paintHtml, /Material default/);
  assert.match(paintHtml, /aria-pressed="true"/);
  assert.doesNotMatch(stoneHtml, /selection-color-picker|selection-color-hex/);
  assert.match(stoneHtml, /natural colour/);
  assert.ok(MATERIAL_COLOR_PRESETS.length > 0);
});

test("preset and custom HEX colours use the existing selection PUT payload", async () => {
  const selection = { component_id: "cmp_wall", material_id: paint.id, params: {} };
  const payloads = [];
  const screen = Object.create(materialsScreen);
  screen.selectedComponentId = "cmp_wall";
  screen.customColorEnabled = false;
  screen.noteDraft = "";
  screen.ctx = {
    projectId: "prj_one",
    store: { getState: (key) => key === "catalogue" ? catalogue : null },
    api: {
      setSelection: async (...args) => payloads.push(args),
    },
    ui: { showToast() {} },
  };
  screen.refreshVariantData = async () => {};
  const variant = { id: "var_one", selections: [selection] };

  await screen.selectColor(MATERIAL_COLOR_PRESETS[0].value, variant);
  await screen.selectColor("#123AbC", variant);

  assert.deepEqual(payloads.map((call) => call[3]), [
    { material_id: paint.id, params: { color_hex: MATERIAL_COLOR_PRESETS[0].value } },
    { material_id: paint.id, params: { color_hex: "#123ABC" } },
  ]);
});

test("color validation and material category guard prevent unsupported colour writes", async () => {
  const payloads = [];
  const toasts = [];
  const screen = Object.create(materialsScreen);
  screen.selectedComponentId = "cmp_wall";
  screen.ctx = {
    store: { getState: (key) => key === "catalogue" ? catalogue : null },
    api: { setSelection: async (...args) => payloads.push(args) },
    ui: { showToast: (message) => toasts.push(message) },
  };
  const variant = {
    id: "var_one",
    selections: [{ component_id: "cmp_wall", material_id: stone.id, params: {} }],
  };

  await screen.selectColor("#12345", variant);
  await screen.selectColor("#123456", variant);

  assert.equal(payloads.length, 0);
  assert.equal(toasts.length, 2);
});

test("material save confirms only after refresh; a failed save remains unselected", async () => {
  const oldSelection = { component_id: "cmp_wall", material_id: stone.id, params: {} };
  const messages = [];
  const component = {
    id: "cmp_wall",
    label: "Front wall",
    type: "wall",
    supported: true,
    box: { x: 0.1, y: 0.1, w: 0.8, h: 0.8 },
  };
  let variants = [{ id: "var_one", selections: [oldSelection] }];
  let renderedPanel = "";
  const screen = Object.create(materialsScreen);
  screen.selectedComponentId = "cmp_wall";
  screen.components = () => [component];
  screen.container = { querySelector: () => ({}) };
  screen.render = async () => {
    const saved = variants[0].selections[0];
    renderedPanel = screen.renderChoicePanel({
      selectedComponent: component,
      selection: saved,
      catalogue,
      compatible: [paint, stone],
      categories: ["paint", "stone_cladding"],
      filtered: [paint, stone],
      activeVariant: variants[0],
      materialById: new Map(catalogue.materials.map((item) => [item.id, item])),
    });
    screen.mountStage(
      { image_url: "/photo" },
      [component],
      new Map([[component.id, saved]]),
      new Map(catalogue.materials.map((item) => [item.id, item]))
    );
  };
  screen.ctx = {
    projectId: "prj_one",
    store: {
      getState: (key) => ({
        catalogue,
        project: { active_variant_id: "var_one" },
        variants,
        generations: [],
      })[key],
      refreshVariants: async () => {},
      refreshGenerations: async () => {},
    },
    api: {
      setSelection: async (_projectId, _variantId, componentId, selection) => {
        variants = [{ id: "var_one", selections: [{ component_id: componentId, ...selection }] }];
      },
    },
    ui: {
      escapeHtml,
      showToast: (message, type) => messages.push({ message, type }),
    },
  };
  await screen.chooseMaterial(paint.id, variants[0]);

  assert.deepEqual(messages.at(-1), {
    message: "Warm paint applied to Front wall.",
    type: "success",
  });
  assert.match(renderedPanel, /Current material: <strong>Warm paint<\/strong>/);
  assert.equal(screen.stage.overlayEl.boxes[0].style.backgroundColor, "rgba(232, 220, 200, 0.48)");
  assert.equal(screen.stage.overlayEl.boxes[0].classes.has("component-box--material-selected"), true);
  messages.length = 0;
  screen.ctx.api.setSelection = async () => { throw new Error("offline"); };
  await screen.chooseMaterial(stone.id, variants[0]);
  assert.equal(variants[0].selections[0].material_id, paint.id);
  assert.equal(screen.stage.overlayEl.boxes[0].style.backgroundColor, "rgba(232, 220, 200, 0.48)");
  assert.equal(messages.some((message) => message.type === "success"), false);
  assert.match(messages[0].message, /offline/);
});

test("narrow layouts stack the panels and keep colour controls usable", async () => {
  const css = await readFile(
    new URL("../static/css/components.css", import.meta.url),
    "utf8"
  );
  assert.match(css, /@media \(max-width: 720px\)[\s\S]*?\.materials-layout\s*\{[^}]*grid-template-columns:\s*1fr/);
  assert.match(css, /@media \(max-width: 720px\)[\s\S]*?\.materials-choice-panel\s*\{[^}]*position:\s*static/);
  assert.match(css, /\.material-color-inputs\s*\{/);
  assert.match(css, /\.material-color-preset\s*\{/);
});

test("bulk application confirms the exact target count before sequential saves", async () => {
  const component = (id, type = "wall", supported = true) => ({
    id,
    type,
    label: id,
    supported,
  });
  const components = [
    component("cmp_source"),
    component("cmp_wall_two"),
    component("cmp_wall_three"),
    component("cmp_door", "door"),
    component("cmp_locked", "wall", false),
  ];
  const confirmations = [];
  const updates = [];
  const screen = Object.create(materialsScreen);
  screen.selectedComponentId = "cmp_source";
  screen.bulkBusy = false;
  screen.components = () => components;
  screen.container = {
    querySelector: () => ({ disabled: false, textContent: "" }),
  };
  screen.ctx = {
    projectId: "prj_one",
    store: { getState: () => [] },
    api: {
      setSelection: async (...args) => updates.push(args[2]),
    },
    ui: {
      confirmModal: async (...args) => {
        confirmations.push(args);
        return true;
      },
      showToast() {},
    },
  };
  screen.refreshVariantData = async () => {};
  const variant = {
    id: "var_one",
    selections: [{ component_id: "cmp_source", material_id: paint.id, params: {} }],
  };

  await screen.applyToAll(variant);

  assert.match(confirmations[0][1], /2 other wall regions/);
  assert.deepEqual(updates, ["cmp_wall_two", "cmp_wall_three"]);
});

test("redesign preferences explain their selected-area and structure limits", async () => {
  const redesign = await readFile(
    new URL("../static/js/screens/redesign.js", import.meta.url),
    "utf8"
  );
  assert.match(redesign, /Additional preferences for the selected areas \(optional\)/);
  assert.match(redesign, /Describe how the selected areas should look/);
  assert.match(redesign, /They do not change unselected regions or the house structure/);
  assert.doesNotMatch(redesign, /keep the garden and the gate exactly as they are/);
});
