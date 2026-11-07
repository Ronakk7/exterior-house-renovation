/**
 * Step 3: Material catalogue, component selections, and design variants.
 */

import { ImageStage } from "../imagestage.js";
import { renderStepper } from "../stepper.js";

export const MATERIAL_COLOR_PRESETS = [
  { label: "Warm beige", value: "#E8DCC8" },
  { label: "Soft ivory", value: "#F5F0E6" },
  { label: "Sandstone", value: "#C9B18C" },
  { label: "Mist grey", value: "#B8C6C9" },
  { label: "Sage", value: "#82918A" },
  { label: "Slate", value: "#59636D" },
];

export function getCompatibleMaterials(catalogue, componentType) {
  return (catalogue?.materials || []).filter((material) =>
    material.compatible_types.includes(componentType)
  );
}

export const materialsScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.stage = null;
    this.loading = true;
    this.loadError = null;
    this.selectedComponentId = null;
    this.categoryFilter = "all";
    this.customColorEnabled = false;
    this.customColor = "";
    this.noteDraft = "";
    this.lastDraftSelectionId = undefined;
    this.lastDraftMaterialId = undefined;
    this.bulkBusy = false;
    await this.load();
  },

  async load() {
    try {
      const [project, photos, components, variants] = await Promise.all([
        this.ctx.api.getProject(this.ctx.projectId),
        this.ctx.api.listPhotos(this.ctx.projectId),
        this.ctx.api.listComponents(this.ctx.projectId),
        this.ctx.api.listVariants(this.ctx.projectId),
      ]);
      if (!this.active) return;
      this.ctx.store.setState("project", project);
      this.ctx.store.setState("activeVariantId", project.active_variant_id);
      this.ctx.store.setState("photos", photos.items || []);
      this.ctx.store.setState("components", components.items || []);
      this.ctx.store.setState("variants", variants.items || []);
      await this.ctx.store.refreshGenerations(
        this.ctx.projectId,
        project.active_variant_id
      );
      let catalogue = this.ctx.store.getState("catalogue");
      if (!catalogue) {
        catalogue = await this.ctx.api.getCatalogue();
        if (!this.active) return;
        this.ctx.store.setState("catalogue", catalogue);
      }
      this.selectedComponentId ||= this.components().find((item) => item.supported)?.id || null;
    } catch (error) {
      this.loadError = error;
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.loading = false;
      if (this.active) await this.render();
    }
  },

  async render() {
    this.stage?.destroy();
    this.stage = null;
    if (this.loading) {
      this.container.innerHTML = '<div class="loading-state" role="status">Loading materials and designs...</div>';
      return;
    }
    if (this.loadError) {
      this.container.innerHTML = `
        <section class="card detection-error" role="alert">
          <h2>Could not load materials</h2>
          <p>${this.ctx.ui.escapeHtml(this.loadError.message)}</p>
          <button id="materials-retry" class="btn btn-primary" type="button">Retry</button>
        </section>`;
      this.container.querySelector("#materials-retry").addEventListener("click", () => {
        this.loading = true;
        this.loadError = null;
        this.load();
      });
      return;
    }

    const project = this.ctx.store.getState("project");
    const photo = (this.ctx.store.getState("photos") || [])[0];
    const components = this.components();
    const supported = components.filter((item) => item.supported);
    if (!photo || components.length === 0) {
      this.container.innerHTML = `
        <div class="screen-view">
          <h2>Step 3: Choose Materials</h2>
          <section class="prerequisite-panel">
            <p>${!photo ? "Upload a photo first." : "Detect or add regions before choosing materials."}</p>
            <button id="materials-prerequisite" class="btn btn-primary" type="button">
              Go to ${!photo ? "Upload" : "Components"}
            </button>
          </section>
          ${this.renderNavigation()}
        </div>`;
      this.container.querySelector("#materials-prerequisite").addEventListener("click", () => {
        this.ctx.router.navigate(`#/p/${this.ctx.projectId}/${photo ? "components" : "upload"}`);
      });
      this.bindNavigation();
      this.updateStepper();
      return;
    }

    const variants = this.ctx.store.getState("variants") || [];
    const activeId = project?.active_variant_id || this.ctx.store.getState("activeVariantId");
    const activeVariant = variants.find((variant) => variant.id === activeId) || variants[0];
    const selectedComponent = supported.find((item) => item.id === this.selectedComponentId)
      || supported[0]
      || null;
    this.selectedComponentId = selectedComponent?.id || null;
    const selection = activeVariant?.selections?.find(
      (item) => item.component_id === selectedComponent?.id
    ) || null;
    this.syncSelectionDraft(selection);
    const catalogue = this.ctx.store.getState("catalogue");
    const materialById = new Map((catalogue?.materials || []).map((item) => [item.id, item]));
    const selectionMap = new Map(
      (activeVariant?.selections || []).map((item) => [item.component_id, item])
    );
    const compatible = selectedComponent
      ? getCompatibleMaterials(catalogue, selectedComponent.type)
      : [];
    const categories = [...new Set(compatible.map((material) => material.category))];
    const filtered = this.categoryFilter === "all"
      ? compatible
      : compatible.filter((material) => material.category === this.categoryFilter);
    const chosenCount = supported.filter((item) => selectionMap.has(item.id)).length;
    const latestStale = (this.ctx.store.getState("generations") || []).some(
      (generation) => generation.status === "succeeded" && generation.is_stale
    );

    this.container.innerHTML = `
      <div class="screen-view">
        <header class="mb-lg">
          <h2>Step 3: Choose Materials &amp; Designs</h2>
          <p class="text-muted">Choose compatible finishes for each customisable region. Catalogue rates are placeholders.</p>
        </header>
        <section class="variant-toolbar card" aria-label="Design variants">
          <label for="variant-select">Design</label>
          <select id="variant-select">
            ${variants.map((variant) => `
              <option value="${this.ctx.ui.escapeHtml(variant.id)}" ${variant.id === activeVariant?.id ? "selected" : ""}>
                ${this.ctx.ui.escapeHtml(variant.name)} (${variant.selections.length} choices)
              </option>`).join("")}
          </select>
          <button id="variant-new" class="btn btn-secondary" type="button" ${variants.length >= 10 ? "disabled" : ""}>New</button>
          <button id="variant-duplicate" class="btn btn-secondary" type="button" ${variants.length >= 10 ? "disabled" : ""}>Duplicate</button>
          <button id="variant-rename" class="btn btn-secondary" type="button">Rename</button>
          <button id="variant-delete" class="btn btn-danger" type="button" ${variants.length <= 1 ? "disabled" : ""}>Delete</button>
        </section>
        ${variants.length >= 10 ? '<p class="component-limit-notice" role="status">This project has reached the 10-design limit.</p>' : ""}
        ${latestStale ? '<p class="detection-advisory" role="status">Your redesign is outdated. Generate it again on the next step.</p>' : ""}
        <p class="selection-summary" role="status">${chosenCount} of ${supported.length} customisable regions have a material.</p>
        <div class="materials-layout">
          <section class="materials-photo-panel card">
            <p class="materials-stage-help">Click a highlighted area or choose a region from the list to customize it.</p>
            <div id="materials-stage"></div>
            <ul class="materials-region-list" aria-label="House regions">
              ${components.map((component) => {
                const current = selectionMap.get(component.id);
                const material = current ? materialById.get(current.material_id) : null;
                return `<li>
                  <button class="materials-region ${component.id === selectedComponent?.id ? "materials-region--selected" : ""} ${component.supported ? "" : "materials-region--unsupported"}"
                    data-component-id="${this.ctx.ui.escapeHtml(component.id)}" type="button"
                    ${component.supported
                      ? `aria-pressed="${component.id === selectedComponent?.id}"`
                      : `disabled aria-label="${this.ctx.ui.escapeHtml(component.label)}, ${this.ctx.ui.escapeHtml(typeLabel(component.type))}, not customisable"`}>
                    <span>${this.ctx.ui.escapeHtml(component.label)} <small>(${this.ctx.ui.escapeHtml(typeLabel(component.type))})</small></span>
                    <span>${component.supported
                      ? material
                        ? `${this.swatch(current.params?.color_hex || material.swatch_hex)}${this.ctx.ui.escapeHtml(material.name)}`
                        : "Choose material"
                      : "Not customisable"}</span>
                    <span class="materials-region__status" aria-hidden="true">${component.supported
                      ? material ? "✓ Chosen" : component.id === selectedComponent?.id ? "Selected" : "Available"
                      : "Unavailable"}</span>
                  </button>
                </li>`;
              }).join("")}
            </ul>
          </section>
          <section id="materials-choice-panel" class="materials-choice-panel card" aria-label="Materials for selected region">
            ${this.renderChoicePanel({
              selectedComponent,
              selection,
              catalogue,
              compatible,
              categories,
              filtered,
              activeVariant,
              materialById,
            })}
          </section>
        </div>
        <nav class="screen-nav" aria-label="Screen navigation">
          <button id="btn-back" class="btn btn-secondary" type="button">&larr; Back to Components</button>
          <button id="btn-next" class="btn btn-primary" type="button">Next: Generate redesign &rarr;</button>
        </nav>
      </div>`;

    this.mountStage(photo, components, selectionMap, materialById);
    this.bindNavigation();
    this.container.querySelector("#variant-select").addEventListener("change", (event) => {
      this.switchVariant(event.target.value);
    });
    this.container.querySelector("#variant-new").addEventListener("click", () => this.createVariant(false, activeVariant));
    this.container.querySelector("#variant-duplicate").addEventListener("click", () => this.createVariant(true, activeVariant));
    this.container.querySelector("#variant-rename").addEventListener("click", () => this.renameVariant(activeVariant));
    this.container.querySelector("#variant-delete").addEventListener("click", () => this.deleteVariant(activeVariant));
    this.bindRegionList();
    this.bindChoicePanel(activeVariant);
    this.updateStepper();
  },

  renderChoicePanel({ selectedComponent, selection, catalogue, compatible, categories, filtered, activeVariant, materialById }) {
    if (!selectedComponent) {
      return "<p>No customisable regions are available. You can continue without material choices.</p>";
    }
    const selectedMaterial = selection ? materialById.get(selection.material_id) : null;
    return `
      <header class="materials-choice-header">
        <div>
          <h3>${this.ctx.ui.escapeHtml(selectedComponent.label)}</h3>
          <p class="text-muted">${this.ctx.ui.escapeHtml(typeLabel(selectedComponent.type))}</p>
        </div>
        <p class="materials-current-choice">${selectedMaterial
          ? `Current material: <strong>${this.ctx.ui.escapeHtml(selectedMaterial.name)}</strong>`
          : "No material selected yet"}</p>
      </header>
      <div class="material-category-filter" role="group" aria-label="Filter material category">
        <button class="btn btn-secondary ${this.categoryFilter === "all" ? "is-selected" : ""}" data-category="all" type="button">All</button>
        ${categories.map((category) => `
          <button class="btn btn-secondary ${this.categoryFilter === category ? "is-selected" : ""}"
            data-category="${this.ctx.ui.escapeHtml(category)}" type="button">
            ${this.ctx.ui.escapeHtml(categoryName(catalogue, category))}
          </button>`).join("")}
      </div>
      <div class="material-cards">
        ${filtered.map((material) => this.renderMaterialCard(material, selection)).join("")}
      </div>
      ${selection ? `
        <div class="selection-options">
          ${selectedMaterial && ["paint", "texture"].includes(selectedMaterial.category)
            ? this.renderColorOptions(selection, selectedMaterial)
            : selectedMaterial
              ? '<p class="text-muted material-color-hint">This finish uses the material&#39;s natural colour. Choose another compatible finish to change its tone.</p>'
              : ""}
          <label for="selection-note">Note for this selected region (optional)</label>
          <input id="selection-note" type="text" maxlength="100" value="${this.ctx.ui.escapeHtml(this.noteDraft)}"
            placeholder="Context for this surface only">
          <button id="clear-selection" class="btn btn-secondary" type="button">Clear choice</button>
          ${this.renderApplyAll(selectedComponent)}
        </div>` : ""}
      ${compatible.length === 0 ? '<p class="text-muted">No compatible catalogue materials are available for this region.</p>' : ""}`;
  },

  renderColorOptions(selection, material) {
    const selectedColor = selection.params?.color_hex || material.swatch_hex;
    const colorOptions = [
      { label: "Material default", value: material.swatch_hex.toUpperCase() },
      ...MATERIAL_COLOR_PRESETS.filter(
        (preset) => preset.value !== material.swatch_hex.toUpperCase()
      ),
    ];
    if (!colorOptions.some((preset) => preset.value === selectedColor.toUpperCase())) {
      colorOptions.unshift({ label: "Current colour", value: selectedColor.toUpperCase() });
    }
    return `
      <fieldset class="material-color-options">
        <legend>Choose a colour</legend>
        <p class="text-muted">${selection.params?.color_hex ? "Custom colour selected" : "Using the material's default colour"}</p>
        <div class="material-color-presets" aria-label="Preset colours">
          ${colorOptions.map((preset) => `
            <button class="material-color-preset ${selectedColor.toUpperCase() === preset.value ? "is-selected" : ""}"
              type="button" data-color="${preset.value}" aria-label="${preset.label} ${preset.value}"
              aria-pressed="${selectedColor.toUpperCase() === preset.value}"
              style="--preset-color:${preset.value}">
              ${selectedColor.toUpperCase() === preset.value ? "✓" : ""}
            </button>`).join("")}
        </div>
        <label for="selection-color-picker">Choose any colour</label>
        <div class="material-color-inputs">
          <input id="selection-color-picker" type="color" aria-label="Choose a custom colour"
            value="${this.ctx.ui.escapeHtml(selectedColor)}">
          <label class="sr-only" for="selection-color-hex">HEX colour</label>
          <input id="selection-color-hex" type="text" maxlength="7" pattern="#[0-9A-Fa-f]{6}"
            aria-label="HEX colour" value="${this.ctx.ui.escapeHtml(selectedColor)}">
        </div>
      </fieldset>`;
  },

  bindChoicePanel(variant) {
    this.container.querySelectorAll("[data-category]").forEach((button) => {
      button.addEventListener("click", () => {
        this.categoryFilter = button.dataset.category;
        this.updateMaterialPanel();
      });
    });
    this.container.querySelectorAll("[data-material-id]").forEach((button) => {
      button.addEventListener("click", () => this.chooseMaterial(button.dataset.materialId, variant));
    });
    this.container.querySelectorAll("[data-color]").forEach((button) => {
      button.addEventListener("click", () => this.selectColor(button.dataset.color, variant));
    });
    this.container.querySelector("#selection-color-picker")?.addEventListener("change", (event) => {
      this.selectColor(event.target.value, variant);
    });
    this.container.querySelector("#selection-color-hex")?.addEventListener("change", (event) => {
      this.selectColor(event.target.value.trim(), variant);
    });
    this.container.querySelector("#selection-note")?.addEventListener("blur", async (event) => {
      this.noteDraft = event.target.value;
      await this.saveCurrentParams(variant);
    });
    this.container.querySelector("#clear-selection")?.addEventListener("click", () => {
      this.clearSelection(variant);
    });
    this.container.querySelector("#apply-all")?.addEventListener("click", () => {
      this.applyToAll(variant);
    });
  },

  bindRegionList() {
    this.container.querySelectorAll(".materials-region").forEach((button) => {
      button.addEventListener("click", () => this.selectComponent(button.dataset.componentId));
    });
  },

  async selectComponent(componentId) {
    if (!this.components().some((component) => component.id === componentId && component.supported)) return;
    this.selectedComponentId = componentId;
    this.categoryFilter = "all";
    await this.updateMaterialPanel();
    if (typeof window !== "undefined" && window.matchMedia?.("(max-width: 720px)").matches) {
      this.container.querySelector("#materials-choice-panel")?.scrollIntoView?.({
        behavior: "smooth",
        block: "start",
      });
    }
  },

  async updateMaterialPanel() {
    const project = this.ctx.store.getState("project");
    const variants = this.ctx.store.getState("variants") || [];
    const activeId = project?.active_variant_id || this.ctx.store.getState("activeVariantId");
    const activeVariant = variants.find((variant) => variant.id === activeId) || variants[0];
    const components = this.components();
    const selectedComponent = components.find((item) => item.id === this.selectedComponentId && item.supported) || null;
    const selection = activeVariant?.selections?.find(
      (item) => item.component_id === selectedComponent?.id
    ) || null;
    this.syncSelectionDraft(selection);
    const catalogue = this.ctx.store.getState("catalogue");
    const materialById = new Map((catalogue?.materials || []).map((item) => [item.id, item]));
    const compatible = selectedComponent
      ? getCompatibleMaterials(catalogue, selectedComponent.type)
      : [];
    const categories = [...new Set(compatible.map((material) => material.category))];
    const filtered = this.categoryFilter === "all"
      ? compatible
      : compatible.filter((material) => material.category === this.categoryFilter);
    const panel = this.container.querySelector("#materials-choice-panel");
    if (!panel) return;
    panel.innerHTML = this.renderChoicePanel({
      selectedComponent,
      selection,
      catalogue,
      compatible,
      categories,
      filtered,
      activeVariant,
      materialById,
    });
    this.container.querySelectorAll(".materials-region").forEach((button) => {
      const selected = button.dataset.componentId === selectedComponent?.id;
      const saved = activeVariant?.selections?.some(
        (item) => item.component_id === button.dataset.componentId
      );
      button.classList.toggle("materials-region--selected", selected);
      if (button.disabled !== true) button.setAttribute("aria-pressed", String(selected));
      const status = button.querySelector(".materials-region__status");
      if (status && button.disabled !== true) {
        status.textContent = saved
          ? selected ? "Chosen · Selected" : "Chosen"
          : selected ? "Selected" : "Available";
      }
    });
    this.stage?.overlayEl?.querySelectorAll(".component-box").forEach((box) => {
      box.classList.toggle("component-box--material-selected", box.getAttribute("data-id") === selectedComponent?.id);
    });
    this.bindChoicePanel(activeVariant);
  },

  renderMaterialCard(material, selection) {
    const chosen = selection?.material_id === material.id;
    const unit = material.pricing_unit === "rft" ? "per running ft" : "per sq ft";
    return `
      <article class="material-card ${chosen ? "material-card--selected" : ""}">
        <button class="material-card__select" type="button"
          data-material-id="${this.ctx.ui.escapeHtml(material.id)}" aria-pressed="${chosen}">
          <span class="material-card__preview material-preview--${this.ctx.ui.escapeHtml(material.category)}"
            style="--material-color:${this.ctx.ui.escapeHtml(material.swatch_hex)}" aria-hidden="true">
            ${chosen ? '<span class="material-card__check" aria-hidden="true">✓ Selected</span>' : ""}
          </span>
          <span class="material-card__heading"><strong>${this.ctx.ui.escapeHtml(material.name)}</strong>
            <span class="badge">${this.ctx.ui.escapeHtml(categoryName(this.ctx.store.getState("catalogue"), material.category))}</span></span>
          <span class="material-card__appearance">${this.ctx.ui.escapeHtml(material.prompt_description)}</span>
          <span class="material-card__unit">${this.ctx.ui.escapeHtml(unit)}</span>
        </button>
        <details class="material-card__details">
          <summary>Details</summary>
          <p><strong>Maintenance:</strong> ${this.ctx.ui.escapeHtml(material.maintenance_note)}</p>
          <p><strong>Durability:</strong> ${this.ctx.ui.escapeHtml(material.durability_note)}</p>
        </details>
      </article>`;
  },

  renderApplyAll(component) {
    const sameType = this.components().filter(
      (item) => item.supported && item.type === component.type && item.id !== component.id
    );
    return sameType.length
      ? `<button id="apply-all" class="btn btn-secondary" type="button" ${this.bulkBusy ? "disabled" : ""}>
          Apply this choice to all ${sameType.length} other ${this.ctx.ui.escapeHtml(typeLabel(component.type))} region${sameType.length === 1 ? "" : "s"}
        </button>`
      : "";
  },

  mountStage(photo, components, selectionMap, materialById) {
    this.stage = new ImageStage(this.container.querySelector("#materials-stage"), photo.image_url);
    const ordered = [...components].sort((a, b) => boxArea(b.box) - boxArea(a.box));
    this.stage.renderBoxes(ordered);
    for (const component of components) {
      const box = [...this.stage.overlayEl.querySelectorAll(".component-box")]
        .find((element) => element.getAttribute("data-id") === component.id);
      const selection = selectionMap.get(component.id);
      const material = selection ? materialById.get(selection.material_id) : null;
      if (box && component.supported && material) {
        box.style.backgroundColor = toRgba(selection.params?.color_hex || material.swatch_hex, 0.48);
      }
      if (box) box.classList.toggle("component-box--material-selected", component.id === this.selectedComponentId);
    }
    this.stage.onBoxClick((id) => {
      this.selectComponent(id);
    });
  },

  syncSelectionDraft(selection) {
    const params = selection?.params || {};
    const enabled = Object.hasOwn(params, "color_hex");
    if (this.lastDraftSelectionId === selection?.component_id
      && this.lastDraftMaterialId === selection?.material_id) return;
    this.lastDraftSelectionId = selection?.component_id || null;
    this.lastDraftMaterialId = selection?.material_id || null;
    this.customColorEnabled = enabled;
    this.customColor = params.color_hex || "";
    this.noteDraft = params.note || "";
  },

  async switchVariant(variantId) {
    try {
      const project = await this.ctx.api.updateProject(this.ctx.projectId, { active_variant_id: variantId });
      this.ctx.store.setState("project", project);
      this.ctx.store.setState("activeVariantId", project.active_variant_id);
      await Promise.all([
        this.ctx.store.refreshVariants(this.ctx.projectId),
        this.ctx.store.refreshGenerations(this.ctx.projectId, variantId),
      ]);
      this.lastDraftSelectionId = null;
      this.selectedComponentId = this.components().find((component) => component.supported)?.id || null;
      await this.render();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      await this.load();
    }
  },

  async createVariant(duplicate, activeVariant) {
    const defaultName = duplicate ? `${activeVariant?.name || "Design"} copy` : this.nextName();
    const name = window.prompt(duplicate ? "Name the copied design" : "Name the new design", defaultName);
    if (name === null) return;
    try {
      const variant = await this.ctx.api.createVariant(this.ctx.projectId, {
        name,
        ...(duplicate && activeVariant ? { copy_from_variant_id: activeVariant.id } : {}),
      });
      await this.activateVariant(variant.id);
      this.ctx.ui.showToast(duplicate ? "Design copied." : "Design created.", "success");
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      if (error.code === "CONFLICT" && error.details?.reason === "variant_limit") await this.load();
    }
  },

  async renameVariant(variant) {
    if (!variant) return;
    const name = window.prompt("Rename this design", variant.name);
    if (name === null || name.trim() === variant.name) return;
    try {
      await this.ctx.api.updateVariant(this.ctx.projectId, variant.id, { name });
      await this.refreshVariantData();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async deleteVariant(variant) {
    if (!variant) return;
    const accepted = await this.ctx.ui.confirmModal(
      "Delete design?",
      "This removes the design, its material choices, and its generated images."
    );
    if (!accepted) return;
    try {
      await this.ctx.api.deleteVariant(this.ctx.projectId, variant.id);
      await this.load();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async activateVariant(variantId) {
    const project = await this.ctx.api.updateProject(this.ctx.projectId, { active_variant_id: variantId });
    this.ctx.store.setState("project", project);
    this.ctx.store.setState("activeVariantId", project.active_variant_id);
    await this.refreshVariantData();
    this.selectedComponentId = this.components().find((component) => component.supported)?.id || null;
  },

  async refreshVariantData() {
    await Promise.all([
      this.ctx.store.refreshVariants(this.ctx.projectId),
      this.ctx.store.refreshGenerations(
        this.ctx.projectId,
        this.ctx.store.getState("project")?.active_variant_id
      ),
    ]);
    this.lastDraftSelectionId = null;
    await this.render();
  },

  async chooseMaterial(materialId, variant) {
    const material = this.ctx.store.getState("catalogue").materials.find((item) => item.id === materialId);
    if (!material) return;
    const previous = variant.selections.find((item) => item.component_id === this.selectedComponentId);
    const params = {};
    if (previous?.params?.note) params.note = previous.params.note;
    if (["paint", "texture"].includes(material.category) && this.customColorEnabled) {
      params.color_hex = this.customColor || material.swatch_hex;
    }
    this.lastDraftSelectionId = null;
    try {
      await this.ctx.api.setSelection(this.ctx.projectId, variant.id, this.selectedComponentId, {
        material_id: materialId,
        params,
      });
      await this.refreshVariantData();
      const component = this.components().find((item) => item.id === this.selectedComponentId);
      this.ctx.ui.showToast(
        `${material.name} applied to ${component?.label || "region"}.`,
        "success"
      );
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async selectColor(color, variant) {
    if (!/^#[0-9A-Fa-f]{6}$/.test(color)) {
      this.ctx.ui.showToast("Enter a valid colour in #RRGGBB format.", "error");
      return;
    }
    const selection = variant?.selections?.find(
      (item) => item.component_id === this.selectedComponentId
    );
    const material = this.ctx.store.getState("catalogue")?.materials?.find(
      (item) => item.id === selection?.material_id
    );
    if (!material || !["paint", "texture"].includes(material.category)) {
      this.ctx.ui.showToast("Custom colours are available only for paint and texture finishes.", "error");
      return;
    }
    this.customColor = color.toUpperCase();
    this.customColorEnabled = true;
    await this.saveCurrentParams(variant, "Colour saved.");
  },

  async saveCurrentParams(variant, successMessage = null) {
    const selection = variant?.selections?.find((item) => item.component_id === this.selectedComponentId);
    if (!selection) return;
    const material = this.ctx.store.getState("catalogue").materials.find((item) => item.id === selection.material_id);
    const params = {};
    if (this.customColorEnabled && ["paint", "texture"].includes(material.category)) {
      params.color_hex = this.customColor || material.swatch_hex;
    }
    if (this.noteDraft.trim()) params.note = this.noteDraft;
    try {
      await this.ctx.api.setSelection(this.ctx.projectId, variant.id, this.selectedComponentId, {
        material_id: selection.material_id,
        params,
      });
      this.lastDraftSelectionId = null;
      await this.refreshVariantData();
      if (successMessage) this.ctx.ui.showToast(successMessage, "success");
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      this.lastDraftSelectionId = null;
      await this.refreshVariantData();
    }
  },

  async clearSelection(variant) {
    try {
      await this.ctx.api.removeSelection(this.ctx.projectId, variant.id, this.selectedComponentId);
      this.lastDraftSelectionId = null;
      await this.refreshVariantData();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async applyToAll(variant) {
    const component = this.components().find((item) => item.id === this.selectedComponentId);
    const current = variant?.selections?.find((item) => item.component_id === component?.id);
    if (!component || !current || this.bulkBusy) return;
    const targets = this.components().filter(
      (item) => item.supported && item.type === component.type && item.id !== component.id
    );
    if (!targets.length) return;
    const accepted = await this.ctx.ui.confirmModal(
      "Apply this choice to other regions?",
      `This will update ${targets.length} other ${typeLabel(component.type)} region${targets.length === 1 ? "" : "s"}.`
    );
    if (!accepted) return;
    const failures = [];
    this.bulkBusy = true;
    const button = this.container.querySelector("#apply-all");
    if (button) button.disabled = true;
    for (let index = 0; index < targets.length; index += 1) {
      if (button) button.textContent = `Applying ${index + 1} of ${targets.length}...`;
      try {
        await this.ctx.api.setSelection(this.ctx.projectId, variant.id, targets[index].id, {
          material_id: current.material_id,
          params: current.params || {},
        });
      } catch (error) {
        failures.push(`${targets[index].label}: ${error.message}`);
      }
    }
    this.bulkBusy = false;
    if (failures.length) {
      this.ctx.ui.showToast(
        `Applied to ${targets.length - failures.length} of ${targets.length} regions. Some choices could not be applied: ${failures.join("; ")}`,
        "warning",
        6000
      );
    } else {
      this.ctx.ui.showToast(`Choice applied to ${targets.length} regions.`, "success");
    }
    await this.refreshVariantData();
  },

  nextName() {
    const existing = new Set((this.ctx.store.getState("variants") || []).map((variant) => variant.name.toLowerCase()));
    let index = 1;
    while (existing.has(`design ${index}`)) index += 1;
    return `Design ${index}`;
  },

  renderNavigation() {
    return `
      <nav class="screen-nav" aria-label="Screen navigation">
        <button id="btn-back" class="btn btn-secondary" type="button">&larr; Back to Components</button>
        <button id="btn-next" class="btn btn-primary" type="button">Next: Generate redesign &rarr;</button>
      </nav>`;
  },

  bindNavigation() {
    this.container.querySelector("#btn-back")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/components`);
    });
    this.container.querySelector("#btn-next")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/redesign`);
    });
  },

  updateStepper() {
    renderStepper(document.getElementById("workflow-stepper"), "materials", this.ctx.projectId, this.ctx.store);
  },

  components() {
    return this.ctx.store.getState("components") || [];
  },

  swatch(color) {
    return `<span class="material-swatch" style="background-color:${this.ctx.ui.escapeHtml(color)}" aria-hidden="true"></span>`;
  },

  unmount() {
    this.active = false;
    this.stage?.destroy();
    this.stage = null;
    this.container.innerHTML = "";
  },
};

function boxArea(box) {
  return box ? box.w * box.h : 0;
}

function typeLabel(type) {
  return type.replaceAll("_", " ");
}

function categoryName(catalogue, categoryId) {
  return catalogue?.categories?.find((item) => item.id === categoryId)?.name || categoryId;
}

function toRgba(hex, alpha) {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}
