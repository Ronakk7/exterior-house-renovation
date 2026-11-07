/**
 * Step 5: editable measurements, project rates, and server-calculated costs.
 */

export const estimateScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.loading = true;
    this.loadError = null;
    this.refreshing = false;
    this.modeDrafts = new Map();
    this.saveTimers = new Map();
    this.savingMeasurements = new Set();
    await this.load();
  },

  async load() {
    try {
      const [project, photos, components, variants, measurements, rates] = await Promise.all([
        this.ctx.api.getProject(this.ctx.projectId),
        this.ctx.api.listPhotos(this.ctx.projectId),
        this.ctx.api.listComponents(this.ctx.projectId),
        this.ctx.api.listVariants(this.ctx.projectId),
        this.ctx.api.listMeasurements(this.ctx.projectId),
        this.ctx.api.listRates(this.ctx.projectId),
      ]);
      if (!this.active) return;
      this.ctx.store.setState("project", project);
      this.ctx.store.setState("activeVariantId", project.active_variant_id);
      this.ctx.store.setState("photos", photos.items || []);
      this.ctx.store.setState("components", components.items || []);
      this.ctx.store.setState("variants", variants.items || []);
      this.ctx.store.setState("measurements", measurements.items || []);
      this.ctx.store.setState("rates", rates.items || []);
      let catalogue = this.ctx.store.getState("catalogue");
      if (!catalogue) {
        catalogue = await this.ctx.api.getCatalogue();
        if (!this.active) return;
        this.ctx.store.setState("catalogue", catalogue);
      }
      if (project.active_variant_id) {
        await this.ctx.store.refreshEstimate(this.ctx.projectId, project.active_variant_id);
      }
      if (!this.active) return;
      this.loadError = null;
    } catch (error) {
      this.loadError = error;
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.loading = false;
      if (this.active) await this.render();
    }
  },

  async render() {
    if (this.loading) {
      this.container.innerHTML = '<div class="loading-state" role="status">Loading measurements and estimate...</div>';
      return;
    }
    if (this.loadError) {
      this.container.innerHTML = `
        <section class="card detection-error" role="alert">
          <h2>Could not load estimate</h2>
          <p>${this.ctx.ui.escapeHtml(this.loadError.message)}</p>
          <button id="estimate-retry" class="btn btn-primary" type="button">Retry</button>
        </section>`;
      this.container.querySelector("#estimate-retry").addEventListener("click", () => {
        this.loading = true;
        this.loadError = null;
        this.load();
      });
      return;
    }

    const project = this.ctx.store.getState("project");
    const variants = this.ctx.store.getState("variants") || [];
    const variant = variants.find((item) => item.id === project?.active_variant_id) || null;
    const photos = this.ctx.store.getState("photos") || [];
    const components = this.ctx.store.getState("components") || [];
    const measurements = new Map(
      (this.ctx.store.getState("measurements") || []).map((item) => [item.component_id, item])
    );
    const catalogue = this.ctx.store.getState("catalogue") || { materials: [], categories: [] };
    const materials = new Map(catalogue.materials.map((item) => [item.id, item]));
    const estimate = this.ctx.store.getState("estimate");
    const selections = variant?.selections || [];
    const componentById = new Map(components.map((item) => [item.id, item]));
    const selectedRows = selections
      .map((selection) => ({
        selection,
        component: componentById.get(selection.component_id),
        material: materials.get(selection.material_id),
        measurement: measurements.get(selection.component_id),
      }))
      .filter((row) => row.component && row.material);
    const estimableRows = selectedRows.filter((row) => !row.measurement);
    const usedMaterialIds = new Set(selectedRows.map((row) => row.material.id));
    const rates = (this.ctx.store.getState("rates") || [])
      .filter((rate) => usedMaterialIds.has(rate.material_id));
    const photo = photos[0] || null;
    const config = this.ctx.store.getState("config") || { currency: "INR", component_types: [] };

    this.container.innerHTML = `
      <div class="screen-view">
        <header class="mb-lg">
          <h2>Step 5: Measurements &amp; estimate</h2>
          <p class="text-muted">Enter approximate sizes. The server calculates quantities and costs; the image is not a verified scale. Rendering-based sizes are not verified physical measurements—check them against a known scale or on site.</p>
        </header>
        ${!variant || selections.length === 0 ? `
          <section class="prerequisite-panel">
            <p>Choose at least one material before estimating costs.</p>
            <button id="estimate-go-materials" class="btn btn-primary" type="button">Go to Materials</button>
          </section>` : `
          <section class="card estimate-toolbar">
            <label for="estimate-variant">Design</label>
            <select id="estimate-variant">
              ${variants.map((item) => `
                <option value="${this.ctx.ui.escapeHtml(item.id)}" ${item.id === variant.id ? "selected" : ""}>
                  ${this.ctx.ui.escapeHtml(item.name)}
                </option>`).join("")}
            </select>
            <label for="floor-count">Floors (optional AI hint)</label>
            <input id="floor-count" type="number" min="1" max="6" step="1"
              value="${project.floor_count ?? ""}" placeholder="Not set">
            <details class="estimate-explainer">
              <summary>How this estimate works</summary>
              <ol>
                <li>You enter width and height, area, or railing length. Optional AI suggestions are approximate and editable.</li>
                <li>Opening areas are subtracted from gross surface area.</li>
                <li>Wastage is added for material quantity; purchase quantity is approximate.</li>
                <li>Material and labour costs use editable rates.</li>
                <li>Ranges reflect measurement uncertainty and are summed across line items.</li>
              </ol>
            </details>
          </section>

          <section class="card estimate-measurements">
            <div class="card-header">
              <div>
                <h3 class="card-title">Measurements</h3>
                <p class="text-muted">Sizes are approximate. AI suggestions are labelled and editable; user-provided measurements take precedence. Rendering-based dimensions require physical verification.</p>
              </div>
              <button id="estimate-ai" class="btn btn-secondary" type="button"
                ${estimableRows.length === 0 ? "disabled" : ""}>
                Estimate missing sizes with AI
              </button>
            </div>
            <label for="estimate-reference-note">Anything the AI should know? (optional)</label>
            <input id="estimate-reference-note" type="text" maxlength="200"
              placeholder="e.g. the front door is about 7 ft tall">
            ${selectedRows.map((row) => this.renderMeasurementRow(row, photo, config)).join("")}
            ${selectedRows.length === 0 ? '<p>No selected components are available for this design.</p>' : ""}
          </section>

          <section class="card estimate-rates">
            <h3 class="card-title">Rates used</h3>
            <p class="text-muted">Catalogue rates are placeholders. Replace them with local quotes.</p>
            <div class="table-scroll">
              <table class="data-table">
                <thead><tr><th>Material</th><th>Unit</th><th>Material rate</th><th>Labour rate</th><th>Wastage %</th><th>Action</th></tr></thead>
                <tbody id="estimate-rates-body">${rates.map((rate) => this.renderRateRow(rate)).join("")}</tbody>
              </table>
            </div>
          </section>
          <section id="estimate-breakdown" class="card estimate-breakdown" aria-live="polite">
            <div class="card-header">
              <h3 class="card-title">Cost breakdown</h3>
              ${this.refreshing ? '<span class="text-muted" role="status">Updating…</span>' : '<span class="badge badge--approximate">Approximate</span>'}
            </div>
            ${this.renderBreakdown(estimate, catalogue, config.currency)}
          </section>`}
        <nav class="screen-nav" aria-label="Screen navigation">
          <button id="estimate-back" class="btn btn-secondary" type="button">&larr; Back to Redesign</button>
          <button id="estimate-next" class="btn btn-primary" type="button">Next: Create report &rarr;</button>
        </nav>
      </div>`;

    this.bindNavigation();
    this.container.querySelector("#estimate-go-materials")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/materials`);
    });
    this.container.querySelector("#estimate-variant")?.addEventListener("change", (event) => {
      this.switchVariant(event.target.value);
    });
    this.container.querySelector("#floor-count")?.addEventListener("change", (event) => {
      this.saveFloorCount(event.target.value);
    });
    this.container.querySelector("#estimate-ai")?.addEventListener("click", () => this.requestAI(estimableRows));
    this.container.querySelectorAll(".measurement-form").forEach((form) => this.bindMeasurementForm(form));
    this.container.querySelectorAll(".rate-field").forEach((input) => {
      input.addEventListener("blur", () => this.saveRateField(input));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.blur();
        }
      });
    });
    this.container.querySelectorAll("[data-reset-rate]").forEach((button) => {
      button.addEventListener("click", () => this.resetRate(button.dataset.resetRate));
    });
  },

  renderMeasurementRow(row, photo, config) {
    const { component, material, measurement } = row;
    const sqft = material.pricing_unit === "sqft";
    const mode = this.modeDrafts.get(component.id)
      || measurement?.input_mode
      || (sqft ? "dimensions" : "length");
    const unitLabel = sqft ? "sq ft" : "ft";
    const componentType = config.component_types.find((item) => item.type === component.type)?.label || component.type;
    return `
      <article class="estimate-measurement-row ${measurement?.source === "ai_estimate" ? "estimate-measurement-row--ai" : ""}">
        <div class="estimate-measurement-preview">
          ${photo ? `<img src="${this.ctx.ui.escapeHtml(photo.image_url)}" alt="Original house photo with ${this.ctx.ui.escapeHtml(component.label)} highlighted">
            <span class="estimate-region-box" aria-hidden="true" style="left:${component.box.x * 100}%;top:${component.box.y * 100}%;width:${component.box.w * 100}%;height:${component.box.h * 100}%"></span>` : ""}
        </div>
        <form class="measurement-form" data-component-id="${this.ctx.ui.escapeHtml(component.id)}">
          <div class="estimate-region-heading">
            <div><h4>${this.ctx.ui.escapeHtml(component.label)}</h4><span class="text-muted">${this.ctx.ui.escapeHtml(componentType)} · ${this.ctx.ui.escapeHtml(material.name)}</span></div>
            ${measurement ? `<span class="badge ${measurement.source === "ai_estimate" ? "badge--approximate" : "badge--success"}">${measurement.source === "ai_estimate" ? "AI estimate" : "Your value"}</span>` : '<span class="badge badge--warning">Needs measurement</span>'}
          </div>
          ${measurement && !this.measurementFits(measurement, material) ? '<p class="inline-error">This measurement no longer fits the region type. Please enter it again.</p>' : ""}
          <div class="estimate-input-grid">
            <label>Measurement mode
              <select data-field="input_mode">
                ${sqft ? `
                  <option value="dimensions" ${mode === "dimensions" ? "selected" : ""}>Width × height</option>
                  <option value="area" ${mode === "area" ? "selected" : ""}>I know the area</option>` : `<option value="length" selected>Railing length</option>`}
              </select>
            </label>
            ${mode === "dimensions" ? `
              <label>Width (ft)<input data-field="width_ft" type="number" min="0.01" max="1000" step="0.01" placeholder="e.g. 30" value="${measurement?.input_mode === mode ? measurement.width_ft ?? "" : ""}"></label>
              <label>Height (ft)<input data-field="height_ft" type="number" min="0.01" max="1000" step="0.01" placeholder="e.g. 10" value="${measurement?.input_mode === mode ? measurement.height_ft ?? "" : ""}"></label>
            ` : ""}
            ${mode === "area" ? `<label>Area (sq ft)<input data-field="area_sqft" type="number" min="0.01" max="1000" step="0.01" placeholder="Use this if you know the area" value="${measurement?.input_mode === mode ? measurement.area_sqft ?? "" : ""}"></label>` : ""}
            ${mode === "length" ? `<label>Length (ft)<input data-field="length_ft" type="number" min="0.01" max="1000" step="0.01" placeholder="Measure along the railing" value="${measurement?.input_mode === mode ? measurement.length_ft ?? "" : ""}"></label>` : ""}
            ${sqft ? `<label>Openings to subtract (sq ft)<input data-field="deduction_sqft" type="number" min="0" max="1000000" step="0.01" placeholder="0" value="${measurement?.input_mode === mode ? measurement.deduction_sqft ?? 0 : 0}"></label>` : ""}
            <label>Uncertainty (%)<input data-field="uncertainty_pct" type="number" min="0" max="100" step="1" value="${measurement?.uncertainty_pct ?? 15}"></label>
            <label>Note (optional)<input data-field="note" type="text" maxlength="200" placeholder="e.g. paced out, not exact" value="${this.ctx.ui.escapeHtml(measurement?.note || "")}"></label>
          </div>
          <div class="estimate-measurement-actions">
            ${measurement ? '<button class="btn btn-secondary" data-delete-measurement type="button">Clear measurement</button>' : ""}
            <span data-measurement-error class="inline-error" role="alert"></span>
          </div>
        </form>
      </article>`;
  },

  renderRateRow(rate) {
    const escape = this.ctx.ui.escapeHtml;
    return `<tr>
      <td>${escape(rate.material_name)}${rate.is_overridden ? ' <span class="badge badge--success">Edited</span>' : ""}</td>
      <td>${escape(rate.pricing_unit)}</td>
      ${["material_rate", "labour_rate", "wastage_pct"].map((field) => `
        <td><input class="rate-field" type="number" min="0" max="${field === "wastage_pct" ? "50" : "1000000"}"
          step="0.01" data-material-id="${escape(rate.material_id)}" data-rate-field="${field}"
          aria-label="${field.replaceAll("_", " ")} for ${escape(rate.material_name)}"
          value="${rate[field]}" placeholder="${rate.defaults[field]}"><small>Default ${rate.defaults[field]}</small></td>`).join("")}
      <td><button class="btn btn-secondary btn-sm" data-reset-rate="${escape(rate.material_id)}"
        type="button" ${rate.is_overridden ? "" : "disabled"}>Reset</button></td>
    </tr>`;
  },

  renderBreakdown(estimate, catalogue, currency) {
    if (!estimate) return '<p class="text-muted">Estimate is not available yet.</p>';
    const escape = this.ctx.ui.escapeHtml;
    const categoryNames = new Map((catalogue.categories || []).map((item) => [item.id, item.name]));
    return `
      ${estimate.missing_measurements.length ? `<div class="estimate-missing" role="status">
        <strong>Not included in totals</strong>
        <ul>${estimate.missing_measurements.map((item) => `<li>${escape(item.component_label)} — ${escape(item.material_name)} has no usable measurement</li>`).join("")}</ul>
      </div>` : ""}
      <div class="table-scroll"><table class="data-table">
        <thead><tr><th>Region</th><th>Measure</th><th>Wastage</th><th>Quantity</th><th>Purchase</th><th>Material</th><th>Labour</th><th>Total range</th></tr></thead>
        <tbody>
          ${estimate.line_items.map((item) => `<tr>
            <td>${escape(item.component_label)}<br><small>${escape(item.material_name)} · ${item.measurement_source === "ai_estimate" ? "AI estimate" : "Your value"}</small></td>
            <td>${item.measure_unit === "sqft" ? this.ctx.ui.formatArea(item.measure_value) : this.ctx.ui.formatLength(item.measure_value)}</td>
            <td>${item.wastage_pct}%</td><td>${Number(item.quantity_with_wastage).toFixed(2)} ${escape(item.pricing_unit)}</td>
            <td>${item.purchase_quantity == null ? "—" : `about ${item.purchase_quantity} ${escape(item.purchase_unit)}`}</td>
            <td>${this.ctx.ui.formatCurrency(item.material_cost, currency)}</td>
            <td>${this.ctx.ui.formatCurrency(item.labour_cost, currency)}</td>
            <td>${this.ctx.ui.formatCurrency(item.line_total, currency)}<br><small>${this.ctx.ui.formatCurrency(item.low_total, currency)} – ${this.ctx.ui.formatCurrency(item.high_total, currency)}</small></td>
          </tr>`).join("")}
        </tbody>
        <tbody class="estimate-category-subtotals">
          ${estimate.category_totals.map((category) => `<tr><th>${escape(categoryNames.get(category.category) || category.category)} subtotal</th><td colspan="5"></td><td>${this.ctx.ui.formatCurrency(category.material_cost, currency)} + ${this.ctx.ui.formatCurrency(category.labour_cost, currency)}</td><th>${this.ctx.ui.formatCurrency(category.total, currency)}</th></tr>`).join("")}
        </tbody>
      </table></div>
      <div class="estimate-grand-total">
        <span>Approximate grand total</span>
        <strong>${this.ctx.ui.formatCurrency(estimate.grand_total, currency)}</strong>
        <span>Range: ${this.ctx.ui.formatCurrency(estimate.grand_total_low, currency)} – ${this.ctx.ui.formatCurrency(estimate.grand_total_high, currency)}</span>
      </div>
      <ul class="estimate-disclaimers">${estimate.disclaimers.map((text) => `<li>${escape(text)}</li>`).join("")}</ul>`;
  },

  measurementFits(measurement, material) {
    return material.pricing_unit === "sqft"
      ? ["dimensions", "area"].includes(measurement.input_mode)
      : measurement.input_mode === "length";
  },

  bindMeasurementForm(form) {
    const componentId = form.dataset.componentId;
    const modeSelect = form.querySelector('[data-field="input_mode"]');
    modeSelect.addEventListener("change", () => {
      this.modeDrafts.set(componentId, modeSelect.value);
      this.render();
    });
    form.querySelectorAll("[data-field]").forEach((input) => {
      if (input === modeSelect) return;
      input.addEventListener("input", () => {
        const timer = this.saveTimers.get(componentId);
        clearTimeout(timer);
        this.saveTimers.set(componentId, setTimeout(() => this.saveMeasurement(form), 400));
      });
      input.addEventListener("blur", () => this.saveMeasurement(form));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          this.saveMeasurement(form);
        }
      });
    });
    form.querySelector("[data-delete-measurement]")?.addEventListener("click", () => {
      this.clearMeasurement(componentId, form);
    });
  },

  readMeasurement(form) {
    const value = (name) => form.querySelector(`[data-field="${name}"]`)?.value;
    const mode = value("input_mode");
    const number = (name, fallback = null) => {
      const raw = value(name);
      if (raw === undefined || raw === "") return fallback;
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const payload = {
      input_mode: mode,
      uncertainty_pct: number("uncertainty_pct", 15),
      deduction_sqft: number("deduction_sqft", 0),
      note: value("note") || null,
    };
    if (mode === "dimensions") {
      payload.width_ft = number("width_ft");
      payload.height_ft = number("height_ft");
      if (!(payload.width_ft > 0) || !(payload.height_ft > 0)) return null;
    } else if (mode === "area") {
      payload.area_sqft = number("area_sqft");
      if (!(payload.area_sqft > 0)) return null;
    } else {
      payload.length_ft = number("length_ft");
      if (!(payload.length_ft > 0)) return null;
    }
    return payload;
  },

  async saveMeasurement(form) {
    const timer = this.saveTimers.get(form.dataset.componentId);
    clearTimeout(timer);
    if (this.savingMeasurements.has(form.dataset.componentId)) return;
    const payload = this.readMeasurement(form);
    if (!payload) return;
    const errorEl = form.querySelector("[data-measurement-error]");
    errorEl.textContent = "";
    this.savingMeasurements.add(form.dataset.componentId);
    try {
      await this.ctx.api.setMeasurement(
        this.ctx.projectId, form.dataset.componentId, payload
      );
      await this.refreshEstimateData();
      const current = form.querySelector(".estimate-region-heading .badge");
      if (current) {
        current.textContent = "Your value";
        current.className = "badge badge--success";
      }
    } catch (error) {
      errorEl.textContent = error.message;
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.savingMeasurements.delete(form.dataset.componentId);
    }
  },

  async clearMeasurement(componentId, form) {
    try {
      await this.ctx.api.deleteMeasurement(this.ctx.projectId, componentId);
      this.modeDrafts.delete(componentId);
      await this.load();
    } catch (error) {
      const errorEl = form.querySelector("[data-measurement-error]");
      if (errorEl) errorEl.textContent = error.message;
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async saveRateField(input) {
    if (input.dataset.saving === "true") return;
    const raw = input.value.trim();
    const value = raw === "" ? null : Number(raw);
    if (value !== null && !Number.isFinite(value)) return;
    input.dataset.saving = "true";
    try {
      await this.ctx.api.setRate(this.ctx.projectId, input.dataset.materialId, {
        [input.dataset.rateField]: value,
      });
      await this.refreshEstimateData();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      input.focus();
    } finally {
      input.dataset.saving = "false";
    }
  },

  async resetRate(materialId) {
    try {
      await this.ctx.api.resetRate(this.ctx.projectId, materialId);
      await this.load();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async refreshEstimateData() {
    const [, rates] = await Promise.all([
      this.ctx.store.refreshMeasurements(this.ctx.projectId),
      this.ctx.store.refreshRates(this.ctx.projectId),
    ]);
    const project = this.ctx.store.getState("project");
    const estimate = await this.ctx.store.refreshEstimate(
      this.ctx.projectId, project?.active_variant_id
    );
    const rateBody = this.container.querySelector("#estimate-rates-body");
    const usedMaterialIds = new Set(
      (this.ctx.store.getState("variants") || [])
        .find((item) => item.id === project?.active_variant_id)
        ?.selections.map((item) => item.material_id) || []
    );
    if (rateBody) {
      rateBody.innerHTML = rates
        .filter((rate) => usedMaterialIds.has(rate.material_id))
        .map((rate) => this.renderRateRow(rate))
        .join("");
      rateBody.querySelectorAll(".rate-field").forEach((input) => {
        input.addEventListener("blur", () => this.saveRateField(input));
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            input.blur();
          }
        });
      });
      rateBody.querySelectorAll("[data-reset-rate]").forEach((button) => {
        button.addEventListener("click", () => this.resetRate(button.dataset.resetRate));
      });
    }
    const target = this.container.querySelector("#estimate-breakdown");
    if (target && estimate) {
      target.innerHTML = `
        <div class="card-header">
          <h3 class="card-title">Cost breakdown</h3>
          <span class="badge badge--approximate">Approximate</span>
        </div>
        ${this.renderBreakdown(
          estimate,
          this.ctx.store.getState("catalogue"),
          this.ctx.store.getState("config")?.currency || "INR"
        )}`;
    }
  },

  async requestAI(rows) {
    const note = this.container.querySelector("#estimate-reference-note")?.value || "";
    this.ctx.ui.showBusy("Estimating sizes from your photo...");
    try {
      await this.ctx.api.requestAIEstimate(this.ctx.projectId, {
        component_ids: rows.map((row) => row.component.id),
        reference_note: note,
      });
      await this.load();
      this.ctx.ui.showToast("AI size suggestions added. Please check them.", "success");
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 0, error.requestId);
    } finally {
      this.ctx.ui.hideBusy();
    }
  },

  async switchVariant(variantId) {
    try {
      await this.ctx.api.updateProject(this.ctx.projectId, { active_variant_id: variantId });
      await this.load();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      await this.load();
    }
  },

  async saveFloorCount(raw) {
    const floorCount = raw === "" ? null : Number(raw);
    if (floorCount !== null && (!Number.isInteger(floorCount) || floorCount < 1 || floorCount > 6)) {
      this.ctx.ui.showToast("Floor count must be between 1 and 6.", "warning");
      return;
    }
    try {
      const project = await this.ctx.api.updateProject(this.ctx.projectId, { floor_count: floorCount });
      this.ctx.store.setState("project", project);
      this.ctx.ui.showToast("Floor count saved.", "success");
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async bindNavigation() {
    this.container.querySelector("#estimate-back").addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/redesign`);
    });
    this.container.querySelector("#estimate-next").addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/report`);
    });
  },

  unmount() {
    this.active = false;
    for (const timer of this.saveTimers.values()) clearTimeout(timer);
    this.saveTimers.clear();
    this.container.innerHTML = "";
  },
};
