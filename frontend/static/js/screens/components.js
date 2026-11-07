/**
 * Step 2: Component detection and region editing.
 */

import { ImageStage } from "../imagestage.js";
import { renderStepper } from "../stepper.js";
import { getDetectionViewState } from "../detection-state.js";

export const componentsScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.stage = null;
    this.detectionError = null;
    this.loadError = null;
    this.warnings = [];
    this.manual = false;
    this.loading = true;
    this.mode = "select";
    this.filter = "all";
    this.selectedId = null;
    this.pendingBox = null;
    this.pendingType = null;
    this.pendingLabel = "";
    this.lastUsedType = null;
    this.serverLimitReached = false;
    this.drawingHint = "";
    this.onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      if (this.pendingBox || this.numericOpen) {
        this.pendingBox = null;
        this.numericOpen = false;
        this.mode = "select";
        this.render();
      } else if (this.mode !== "select") {
        this.setMode("select");
      }
    };
    window.addEventListener("keydown", this.onKeyDown);
    await this.render();

    try {
      const photoResult = await ctx.api.listPhotos(ctx.projectId);
      if (!this.active) return;
      const photos = photoResult.items || [];
      ctx.store.setState("photos", photos);
      const components = photos.length
        ? await ctx.api.listComponents(ctx.projectId, photos[0].id)
        : { items: [] };
      if (!this.active) return;
      ctx.store.setState("components", components.items || []);
    } catch (error) {
      if (!this.active) return;
      this.loadError = error;
      ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.loading = false;
    }
    if (this.active) await this.render();
  },

  async render() {
    if (!this.active) return;
    this.stage?.destroy();
    this.stage = null;
    const photos = this.ctx.store.getState("photos") || [];
    const photo = photos[0] || null;
    const components = this.ctx.store.getState("components") || [];
    const state = this.loading
      ? "loading"
      : this.loadError
        ? "load-error"
        : getDetectionViewState(photo, components, this.detectionError, this.manual);

    if (state === "loading") {
      this.container.innerHTML = '<div class="loading-state" role="status">Loading exterior image and regions...</div>';
      return;
    }
    if (state === "no-photo") {
      this.container.innerHTML = `
        <section class="prerequisite-panel">
          <p>Upload a clear exterior photograph or 3D architectural rendering of your house to find and review exterior regions.</p>
          <button id="btn-go-upload" class="btn btn-primary" type="button">Go to Upload</button>
        </section>`;
      this.container.querySelector("#btn-go-upload").addEventListener("click", () => {
        this.ctx.router.navigate(`#/p/${this.ctx.projectId}/upload`);
      });
      return;
    }
    if (state === "load-error") {
      this.container.innerHTML = `
        <section class="card detection-error" role="alert">
          <h2>Could not load this image</h2>
          <p>${this.ctx.ui.escapeHtml(this.loadError?.message || "Please try again.")}</p>
          <button id="btn-retry-load" class="btn btn-primary" type="button">Retry</button>
        </section>`;
      this.container.querySelector("#btn-retry-load").addEventListener("click", () => {
        this.loadError = null;
        this.loading = true;
        this.mount(this.container, this.ctx);
      });
      return;
    }

    const view = state === "empty"
      ? this.renderEmptyState(photo)
      : state === "unusable"
        ? this.renderUnusableState(photo)
        : state === "not-detected"
          ? this.renderNotDetectedState(photo)
          : state === "failed"
            ? this.renderFailedState(photo)
            : this.renderEditor(photo, components);
    this.container.innerHTML = `
      <div class="screen-view">
        <header class="mb-lg">
          <h2>Step 2: Review Exterior Regions</h2>
          <p class="text-muted">Upload a clear exterior photograph or 3D architectural rendering of your house. Detection marks approximate regions; review and correct them before choosing materials.</p>
        </header>
        ${view}
        <nav class="screen-nav" aria-label="Screen navigation">
          <button id="btn-back" class="btn btn-secondary" type="button">&larr; Back to Upload</button>
          <button id="btn-next" class="btn btn-secondary" type="button">Next: Choose materials &rarr;</button>
        </nav>
      </div>`;

    this.container.querySelector("#btn-back").addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/upload`);
    });
    this.container.querySelector("#btn-next").addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/materials`);
    });
    this.container.querySelector("#btn-detect")?.addEventListener("click", () => {
      this.detect(photo);
    });
    this.container.querySelector("#btn-detect-again")?.addEventListener("click", () => {
      this.detect(photo, true);
    });
    this.container.querySelector("#btn-retry-detection")?.addEventListener("click", () => {
      this.detect(photo);
    });
    this.container.querySelector("#btn-draw")?.addEventListener("click", () => {
      this.manual = true;
      this.render();
    });
    this.container.querySelector("#btn-replace")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/upload`);
    });

    if (state === "ready" || state === "manual") {
      this.mountEditor(photo, components);
    }
    this.updateStepper();
  },

  renderNotDetectedState(photo) {
    return `
      <section class="card detection-panel">
        ${this.renderPhoto(photo)}
        <div class="detection-copy">
          <p>We will look for walls, windows, balconies, pillars and other exterior parts. You can review and correct the regions afterwards.</p>
          <button id="btn-detect" class="btn btn-primary" type="button">Detect components</button>
          <button id="btn-draw" class="btn btn-secondary" type="button">Skip and draw regions myself</button>
        </div>
      </section>`;
  },

  renderUnusableState(photo) {
    return `
      <section class="card detection-panel detection-panel--warning">
        ${this.renderPhoto(photo)}
        <div class="detection-copy" role="status">
          <h3>This image may not be usable</h3>
          <p>${this.ctx.ui.escapeHtml(photo.quality_reason || "Please upload a clear exterior photograph or 3D architectural rendering of your house.")}</p>
          <button id="btn-replace" class="btn btn-secondary" type="button">Replace image</button>
          <button id="btn-draw" class="btn btn-primary" type="button">Draw regions anyway</button>
        </div>
      </section>`;
  },

  renderEmptyState(photo) {
    return `
      <section class="card detection-empty" role="status">
        ${this.renderPhoto(photo)}
        ${this.renderAdvisory(photo)}
        <p>No components were found. You can add regions manually.</p>
        ${this.renderWarnings()}
        <div class="detection-actions">
          <button id="btn-detect-again" class="btn btn-primary" type="button">Detect again</button>
          <button id="btn-draw" class="btn btn-secondary" type="button">Draw regions myself</button>
        </div>
      </section>`;
  },

  renderFailedState(photo) {
    return `
      <section class="card detection-panel detection-panel--warning">
        ${this.renderPhoto(photo)}
        <div class="detection-copy" role="alert">
          <h3>Detection did not finish</h3>
          <p>${this.ctx.ui.escapeHtml(this.detectionError?.message || "Please try again.")}</p>
          <button id="btn-retry-detection" class="btn btn-primary" type="button">Try again</button>
          <button id="btn-draw" class="btn btn-secondary" type="button">Draw regions myself</button>
        </div>
      </section>`;
  },

  renderEditor(photo, components) {
    const config = this.ctx.store.getState("config") || {};
    const types = config.component_types || [];
    const maximum = config.limits?.max_components_per_photo;
    const atLimit = this.serverLimitReached
      || (Number.isInteger(maximum) && components.length >= maximum);
    const visible = this.filter === "supported"
      ? components.filter((component) => component.supported)
      : components;
    const selected = components.find((component) => component.id === this.selectedId);
    const summary = `${components.length} regions, ${components.filter((item) => item.supported).length} customisable`;
    const detectionButton = photo.detected_at
      ? '<button id="btn-detect-again" class="btn btn-secondary" type="button">Detect again</button>'
      : '<button id="btn-detect" class="btn btn-secondary" type="button">Detect components</button>';
    return `
      <section class="card detection-editor">
        <header class="detection-toolbar">
          <div>
            <strong>${summary}</strong>
            ${this.renderAdvisory(photo)}
          </div>
          <div class="detection-actions">
            <button id="btn-mode-select" class="btn btn-secondary" type="button">Select</button>
            <button id="btn-add-region" class="btn btn-secondary" type="button" ${atLimit ? "disabled" : ""}>Add region</button>
            <button id="btn-add-numeric" class="btn btn-secondary" type="button" ${atLimit ? "disabled" : ""}>Add region (numeric)</button>
            ${detectionButton}
            <label class="component-filter">
              Show
              <select id="component-filter" aria-label="Filter regions">
                <option value="all" ${this.filter === "all" ? "selected" : ""}>All</option>
                <option value="supported" ${this.filter === "supported" ? "selected" : ""}>Customisable</option>
              </select>
            </label>
          </div>
        </header>
        ${this.renderWarnings()}
        ${atLimit ? `<p class="component-limit-notice" role="status">This image has reached the maximum of ${maximum} regions.</p>` : ""}
        <p class="drawing-hint" aria-live="polite">${this.ctx.ui.escapeHtml(this.drawingHint)}</p>
        <div class="region-editor-layout">
          <div class="region-editor-photo">
            <div id="detection-stage" class="detection-stage"></div>
          </div>
          <aside class="region-editor-panel">
            <h3>Regions (${visible.length})</h3>
            <ul class="detection-region-list" aria-label="Regions">
              ${visible.map((component) => this.renderRegionRow(component)).join("")}
            </ul>
            ${this.pendingBox || this.numericOpen
              ? this.renderPendingForm(types)
              : selected
                ? this.renderDetails(selected, types)
                : '<p class="text-muted">Select a region to review its details.</p>'}
          </aside>
        </div>
      </section>`;
  },

  renderRegionRow(component) {
    const selected = component.id === this.selectedId;
    return `
      <li class="region-row ${selected ? "region-row--selected" : ""}" data-region-id="${this.ctx.ui.escapeHtml(component.id)}"
        tabindex="0" role="button" aria-pressed="${selected}">
        <strong>${this.ctx.ui.escapeHtml(this.typeLabel(component.type))}</strong>
        <span>${this.ctx.ui.escapeHtml(component.label)}</span>
        <span class="badge ${component.supported ? "badge--supported" : "badge--unsupported"}">
          ${component.supported ? "Customisable" : "Not customisable"}
        </span>
        ${component.is_locked ? '<span class="badge badge--locked">Edited by you</span>' : ""}
        ${component.origin === "user" ? '<span class="badge badge--user-value">Added by you</span>' : ""}
        ${component.confidence !== null && component.confidence < 0.5
          ? '<span class="badge badge--approximate">Check this</span>'
          : ""}
      </li>`;
  },

  renderDetails(component, types) {
    return `
      <section class="region-details" aria-label="Selected region details">
        <h3>Selected region</h3>
        <label for="region-type">Type</label>
        <select id="region-type">${this.renderTypeOptions(types, component.type)}</select>
        <label for="region-label">Label</label>
        <input id="region-label" type="text" maxlength="120" value="${this.ctx.ui.escapeHtml(component.label)}">
        <div class="region-detail-actions">
          <button id="btn-redraw" class="btn btn-secondary" type="button">Redraw box</button>
          <button id="btn-delete-region" class="btn btn-danger" type="button">Delete</button>
        </div>
      </section>`;
  },

  renderPendingForm(types) {
    const box = this.pendingBox;
    const percent = (value) => box ? (value * 100).toFixed(1) : "";
    return `
      <form id="pending-region-form" class="region-details">
        <h3>New region</h3>
        <label for="pending-type">Type</label>
        <select id="pending-type" required>${this.renderTypeOptions(types, this.pendingType || this.defaultType(types))}</select>
        <label for="pending-label">Label (optional)</label>
        <input id="pending-label" type="text" maxlength="120" value="${this.ctx.ui.escapeHtml(this.pendingLabel || "")}">
        <fieldset class="numeric-box-fields">
          <legend>Box position and size (%)</legend>
          ${[
            ["left", box?.x],
            ["top", box?.y],
            ["width", box?.w],
            ["height", box?.h],
          ].map(([name, value]) => `
            <label for="box-${name}">${name}</label>
            <input id="box-${name}" name="${name}" type="number" min="${name === "width" || name === "height" ? "2" : "0"}"
              max="100" step="0.1" ${box ? `value="${percent(value)}"` : 'value=""'} required>`).join("")}
        </fieldset>
        <div class="region-detail-actions">
          <button class="btn btn-primary" type="submit">Add region</button>
          <button id="btn-cancel-pending" class="btn btn-secondary" type="button">Cancel</button>
        </div>
      </form>`;
  },

  renderTypeOptions(types, selectedType) {
    return types.map((item) => `
      <option value="${this.ctx.ui.escapeHtml(item.type)}" ${item.type === selectedType ? "selected" : ""}>
        ${this.ctx.ui.escapeHtml(item.label)}${item.supported ? "" : " (not customisable)"}
      </option>`).join("");
  },

  mountEditor(photo, components) {
    const stageContainer = this.container.querySelector("#detection-stage");
    this.stage = new ImageStage(stageContainer, photo.image_url);
    const visible = this.filter === "supported"
      ? components.filter((component) => component.supported)
      : components;
    const ordered = [...visible].sort((a, b) => boxArea(b.box) - boxArea(a.box));
    const shownIds = new Set(visible.map((component) => component.id));
    this.stage.renderBoxes(ordered);
    if (this.selectedId) this.stage.selectBox(this.selectedId);
    this.stage.onBoxClick((id) => {
      if (shownIds.has(id)) this.selectComponent(id);
    });
    this.stage.onBoxHover((id) => this.stage?.highlightBox(id));
    if (this.pendingBox) this.renderPendingBox();
    if (this.mode !== "select") this.activateDrawing();

    this.container.querySelector("#btn-mode-select").addEventListener("click", () => {
      this.setMode("select");
    });
    this.container.querySelector("#btn-add-region").addEventListener("click", () => {
      this.pendingBox = null;
      this.numericOpen = false;
      this.pendingType = this.lastUsedType || this.defaultType(this.ctx.store.getState("config")?.component_types || []);
      this.setMode("add");
    });
    this.container.querySelector("#btn-add-numeric").addEventListener("click", () => {
      this.pendingBox = null;
      this.numericOpen = true;
      this.pendingType = this.lastUsedType || this.defaultType(this.ctx.store.getState("config")?.component_types || []);
      this.setMode("select");
      this.render();
    });
    this.container.querySelector("#component-filter").addEventListener("change", (event) => {
      this.filter = event.target.value;
      if (
        this.filter === "supported"
        && !this.components().find((item) => item.id === this.selectedId)?.supported
      ) {
        this.selectedId = null;
      }
      this.render();
    });
    this.container.querySelectorAll(".region-row").forEach((row) => {
      const select = () => this.selectComponent(row.dataset.regionId);
      row.addEventListener("click", select);
      row.addEventListener("pointerenter", () => this.stage?.highlightBox(row.dataset.regionId));
      row.addEventListener("pointerleave", () => this.stage?.highlightBox(this.selectedId));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
    });

    const typeInput = this.container.querySelector("#region-type");
    typeInput?.addEventListener("change", async (event) => {
      const accepted = await this.ctx.ui.confirmModal(
        "Change region type?",
        "Changing the type may remove material choices that are not compatible. Continue?"
      );
      if (!accepted) {
        await this.render();
        return;
      }
      await this.saveComponent(this.selectedId, { type: event.target.value });
    });
    const labelInput = this.container.querySelector("#region-label");
    labelInput?.addEventListener("blur", () => {
      const component = this.components().find((item) => item.id === this.selectedId);
      if (component && labelInput.value.trim() !== component.label) {
        this.saveComponent(component.id, { label: labelInput.value });
      }
    });
    labelInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        labelInput.blur();
      }
    });
    this.container.querySelector("#btn-redraw")?.addEventListener("click", () => {
      this.setMode("redraw");
    });
    this.container.querySelector("#btn-delete-region")?.addEventListener("click", () => {
      this.removeSelected();
    });
    this.container.querySelector("#pending-type")?.addEventListener("change", (event) => {
      this.pendingType = event.target.value;
    });
    this.container.querySelector("#pending-label")?.addEventListener("input", (event) => {
      this.pendingLabel = event.target.value;
    });
    this.container.querySelector("#pending-region-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submitPendingRegion();
    });
    this.container.querySelector("#btn-cancel-pending")?.addEventListener("click", () => {
      this.pendingBox = null;
      this.numericOpen = false;
      this.pendingLabel = "";
      this.setMode("select");
    });
  },

  renderPendingBox() {
    const box = this.pendingBox;
    const element = document.createElement("div");
    element.className = "component-box component-box--pending";
    element.setAttribute("aria-label", "Pending new region");
    element.style.left = `${box.x * 100}%`;
    element.style.top = `${box.y * 100}%`;
    element.style.width = `${box.w * 100}%`;
    element.style.height = `${box.h * 100}%`;
    this.stage.overlayEl.appendChild(element);
  },

  activateDrawing() {
    if (!this.stage) return;
    const drawingMode = this.mode;
    this.stage.enableDrawing(
      (box) => {
        if (drawingMode === "add") {
          this.pendingBox = box;
          this.numericOpen = false;
          this.pendingLabel = "";
          this.mode = "select";
          this.drawingHint = "";
          this.render();
        } else if (drawingMode === "redraw") {
          this.drawingHint = "";
          this.saveComponent(this.selectedId, { box });
        }
      },
      {
        allowOnComponents: true,
        onTooSmall: () => {
          this.drawingHint = "Drag a larger area.";
          this.render();
        },
      }
    );
  },

  async submitPendingRegion() {
    let box = this.pendingBox;
    if (this.numericOpen) {
      const values = ["left", "top", "width", "height"].map((name) =>
        Number(this.container.querySelector(`#box-${name}`).value)
      );
      if (values.some((value) => !Number.isFinite(value))) {
        this.ctx.ui.showToast("Enter valid position and size values.", "warning");
        return;
      }
      const [x, y, width, height] = values.map((value) => value / 100);
      if (width < 0.02 || height < 0.02 || x < 0 || y < 0 || x + width > 1 || y + height > 1) {
        this.ctx.ui.showToast("The region must be at least 2% wide and high and fit inside the photo.", "warning");
        return;
      }
      box = { x, y, w: width, h: height };
    }
    if (!box) return;
    const photo = (this.ctx.store.getState("photos") || [])[0];
    try {
      const created = await this.ctx.api.createComponent(this.ctx.projectId, {
        photo_id: photo.id,
        type: this.pendingType || this.defaultType(this.ctx.store.getState("config")?.component_types || []),
        label: this.pendingLabel || undefined,
        box,
      });
      this.lastUsedType = created.type;
      this.pendingBox = null;
      this.numericOpen = false;
      this.pendingLabel = "";
      this.selectedId = created.id;
      this.replaceComponent(created);
      this.serverLimitReached = false;
      this.refreshProjectCounts();
    } catch (error) {
      if (error.code === "CONFLICT" && error.details?.reason === "component_limit") {
        this.serverLimitReached = true;
        this.ctx.ui.showToast(error.message, "warning", 6000, error.requestId);
      } else {
        this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      }
    }
    if (this.active) await this.render();
  },

  async saveComponent(componentId, changes) {
    if (!componentId) return;
    try {
      const result = await this.ctx.api.updateComponent(this.ctx.projectId, componentId, changes);
      this.replaceComponent(result.component);
      for (const warning of result.warnings || []) {
        this.ctx.ui.showToast(warning, "warning");
      }
      this.refreshProjectCounts();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      if (error.status === 404) await this.reloadComponents();
    }
    if (this.active) await this.render();
  },

  async removeSelected() {
    const component = this.components().find((item) => item.id === this.selectedId);
    if (!component) return;
    const accepted = await this.ctx.ui.confirmModal(
      "Delete region?",
      "Deleting this region also removes any material choices and measurement attached to it."
    );
    if (!accepted) return;
    try {
      await this.ctx.api.deleteComponent(this.ctx.projectId, component.id);
      this.ctx.store.setState(
        "components",
        this.components().filter((item) => item.id !== component.id)
      );
      this.selectedId = null;
      this.refreshProjectCounts();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      if (error.status === 404) await this.reloadComponents();
    }
    if (this.active) await this.render();
  },

  async detect(photo, confirm = false) {
    if (confirm) {
      const accepted = await this.ctx.ui.confirmModal(
        "Detect components again?",
        "Detecting again replaces the regions that you have not edited. Regions you added or changed are kept. Material choices and measurements linked to replaced regions will be removed. Continue?"
      );
      if (!accepted) return;
    }
    this.detectionError = null;
    this.ctx.ui.showBusy("Analysing your house exterior image...");
    try {
      const result = await this.ctx.api.detectComponents(this.ctx.projectId, photo.id);
      if (!this.active) return;
      this.ctx.store.setState("photos", [result.photo]);
      this.ctx.store.setState("components", result.components || []);
      this.warnings = result.warnings || [];
      this.manual = false;
      this.selectedId = null;
      this.refreshProjectCounts();
      this.updateStepper();
    } catch (error) {
      if (!this.active) return;
      this.detectionError = error;
      this.ctx.ui.showToast(error.message, "error", 0, error.requestId);
    } finally {
      this.ctx.ui.hideBusy();
      if (this.active) await this.render();
    }
  },

  async reloadComponents() {
    const photo = (this.ctx.store.getState("photos") || [])[0];
    if (!photo) return;
    try {
      const result = await this.ctx.api.listComponents(this.ctx.projectId, photo.id);
      this.ctx.store.setState("components", result.items || []);
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  replaceComponent(component) {
    const components = this.components();
    const index = components.findIndex((item) => item.id === component.id);
    const next = [...components];
    if (index < 0) next.push(component);
    else next[index] = component;
    this.ctx.store.setState("components", next);
  },

  refreshProjectCounts() {
    this.ctx.store.refreshProject(this.ctx.projectId).catch((error) => {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    });
  },

  selectComponent(componentId) {
    if (!this.components().some((item) => item.id === componentId)) return;
    this.selectedId = componentId;
    this.render();
  },

  setMode(mode) {
    this.mode = mode;
    this.drawingHint = "";
    this.stage?.disableDrawing();
    if (mode !== "select") this.activateDrawing();
    this.container.querySelector(".image-stage")?.classList.toggle(
      "image-stage--drawing",
      mode !== "select"
    );
    const hint = this.container.querySelector(".drawing-hint");
    if (hint) {
      hint.textContent = mode === "add"
        ? "Drag a rectangle over the image. Press Escape to cancel."
        : mode === "redraw"
          ? "Drag a replacement rectangle. Press Escape to cancel."
          : "";
    }
  },

  renderPhoto(photo) {
    return `
      <div class="detection-photo">
        <img src="${this.ctx.ui.escapeHtml(photo.image_url)}?v=${encodeURIComponent(photo.id)}"
          alt="Original house exterior image">
      </div>`;
  },

  renderAdvisory(photo) {
    return photo.quality_reason && photo.quality_usable
      ? `<p class="detection-advisory">${this.ctx.ui.escapeHtml(photo.quality_reason)}</p>`
      : "";
  },

  renderWarnings() {
    return this.warnings.length
      ? `<ul class="detection-warnings" role="status">${this.warnings
          .map((warning) => `<li>${this.ctx.ui.escapeHtml(warning)}</li>`)
          .join("")}</ul>`
      : "";
  },

  components() {
    return this.ctx.store.getState("components") || [];
  },

  typeLabel(type) {
    const types = this.ctx.store.getState("config")?.component_types || [];
    return types.find((item) => item.type === type)?.label || type.replaceAll("_", " ");
  },

  defaultType(types) {
    return types.find((item) => item.type === "wall")?.type || types[0]?.type || "";
  },

  updateStepper() {
    const stepper = document.getElementById("workflow-stepper");
    renderStepper(stepper, "components", this.ctx.projectId, this.ctx.store);
  },

  unmount() {
    this.active = false;
    this.stage?.destroy();
    this.stage = null;
    window.removeEventListener("keydown", this.onKeyDown);
    this.container.innerHTML = "";
  },
};

function boxArea(box) {
  return box ? box.w * box.h : 0;
}
