/**
 * Step 6: report readiness, PDF generation, and immutable report history.
 */

export const reportScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.loading = true;
    this.loadError = null;
    this.actionError = null;
    this.busy = false;
    this.generationWasChanged = false;
    this.selectedGenerationId = null;
    await this.load();
  },

  async load() {
    try {
      const [project, photos, variants, catalogue, reports, measurements, rates] = await Promise.all([
        this.ctx.api.getProject(this.ctx.projectId),
        this.ctx.api.listPhotos(this.ctx.projectId),
        this.ctx.api.listVariants(this.ctx.projectId),
        this.ctx.api.getCatalogue(),
        this.ctx.api.listReports(this.ctx.projectId),
        this.ctx.api.listMeasurements(this.ctx.projectId),
        this.ctx.api.listRates(this.ctx.projectId),
      ]);
      if (!this.active) return;
      this.ctx.store.setState("project", project);
      this.ctx.store.setState("activeVariantId", project.active_variant_id);
      this.ctx.store.setState("photos", photos.items || []);
      this.ctx.store.setState("variants", variants.items || []);
      this.ctx.store.setState("catalogue", catalogue);
      this.ctx.store.setState("reports", reports.items || []);
      this.ctx.store.setState("measurements", measurements.items || []);
      this.ctx.store.setState("rates", rates.items || []);
      await this.refreshVariantData(project.active_variant_id);
    } catch (error) {
      this.loadError = error;
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.loading = false;
      if (this.active) await this.render();
    }
  },

  async refreshVariantData(variantId) {
    if (!variantId) {
      this.ctx.store.setState("generations", []);
      this.ctx.store.setState("estimate", null);
      this.selectedGenerationId = null;
      return;
    }
    const [generations] = await Promise.all([
      this.ctx.store.refreshGenerations(this.ctx.projectId, variantId),
      this.ctx.store.refreshEstimate(this.ctx.projectId, variantId),
    ]);
    const succeeded = generations.filter((item) => item.status === "succeeded");
    const defaultGeneration = succeeded.find((item) => item.is_approved) || succeeded[0] || null;
    if (!this.generationWasChanged || !succeeded.some((item) => item.id === this.selectedGenerationId)) {
      this.selectedGenerationId = defaultGeneration?.id || null;
      this.generationWasChanged = false;
    }
  },

  async render() {
    if (this.loading) {
      this.container.innerHTML = '<div class="loading-state" role="status">Loading report details...</div>';
      return;
    }
    if (this.loadError) {
      this.container.innerHTML = `
        <section class="card detection-error" role="alert">
          <h2>Could not load reports</h2>
          <p>${this.ctx.ui.escapeHtml(this.loadError.message)}</p>
          <button id="report-retry-load" class="btn btn-primary" type="button">Retry</button>
        </section>`;
      this.container.querySelector("#report-retry-load").addEventListener("click", () => {
        this.loading = true;
        this.loadError = null;
        this.load();
      });
      return;
    }

    const project = this.ctx.store.getState("project");
    const photos = this.ctx.store.getState("photos") || [];
    const variants = this.ctx.store.getState("variants") || [];
    const activeId = project?.active_variant_id || this.ctx.store.getState("activeVariantId");
    const variant = variants.find((item) => item.id === activeId) || variants[0] || null;
    const generations = (this.ctx.store.getState("generations") || [])
      .filter((item) => item.status === "succeeded");
    const selectedGeneration = generations.find((item) => item.id === this.selectedGenerationId) || null;
    const estimate = this.ctx.store.getState("estimate");
    const measurements = this.ctx.store.getState("measurements") || [];
    const rates = this.ctx.store.getState("rates") || [];
    const selectedCount = variant?.selections?.length || 0;
    const materialIds = new Set((variant?.selections || []).map((item) => item.material_id));
    const usedRates = rates.filter((item) => materialIds.has(item.material_id));
    const aiCount = measurements.filter((item) => item.source === "ai_estimate" &&
      (variant?.selections || []).some((selection) => selection.component_id === item.component_id)).length;
    const missingCount = estimate?.missing_measurements?.length || 0;
    const hasDefaultRates = usedRates.some((item) => !item.is_overridden);
    const noPhoto = photos.length === 0;
    const noSelections = !variant || selectedCount === 0;

    this.container.innerHTML = `
      <div class="screen-view report-screen">
        <header class="mb-lg">
          <h2>Step 6: Renovation Summary &amp; PDF Report</h2>
          <p class="text-muted">Create an advisory discussion document for your contractor. Warnings do not prevent report generation.</p>
        </header>
        <section class="card report-toolbar">
          <label for="report-variant">Design</label>
          <select id="report-variant" ${variants.length < 2 ? "disabled" : ""}>
            ${variants.map((item) => `<option value="${this.escape(item.id)}" ${item.id === variant?.id ? "selected" : ""}>${this.escape(item.name)}</option>`).join("")}
          </select>
          <label for="report-generation">Redesign image</label>
          <select id="report-generation" ${generations.length ? "" : "disabled"}>
            ${generations.length
              ? generations.map((item) => `<option value="${this.escape(item.id)}" ${item.id === selectedGeneration?.id ? "selected" : ""}>${this.escape(this.generationLabel(item))}</option>`).join("")
              : '<option value="">No redesign yet. The report will say so.</option>'}
          </select>
          <p class="text-muted report-preview-note">The report includes the approved image, otherwise the newest successful image, unless you choose another image.</p>
        </section>

        ${noPhoto || noSelections ? `
          <section class="prerequisite-panel report-prerequisite">
            <p>${noPhoto ? "Upload a photo before generating a report." : "Choose at least one material for this design before generating a report."}</p>
            <button id="report-go-prerequisite" class="btn btn-primary" type="button">Go to ${noPhoto ? "Upload" : "Materials"}</button>
          </section>` : ""}

        ${this.actionError ? `
          <section class="card detection-error report-action-error" role="alert">
            <p>${this.escape(this.actionError)}</p>
            <button id="report-retry-create" class="btn btn-primary" type="button">Try again</button>
          </section>` : ""}

        <section class="card report-readiness">
          <h3>Readiness</h3>
          <ul>
            <li class="${noPhoto ? "report-warning" : "report-ready"}">${noPhoto ? "WARN" : "OK"} &nbsp; Photo${noPhoto ? " missing" : " available"}</li>
            <li class="${noSelections ? "report-warning" : "report-ready"}">${noSelections ? "WARN" : "OK"} &nbsp; Materials chosen (${selectedCount} regions)</li>
            <li class="${selectedGeneration && !selectedGeneration.is_stale && selectedGeneration.is_approved ? "report-ready" : "report-warning"}">${selectedGeneration && !selectedGeneration.is_stale && selectedGeneration.is_approved ? "OK" : "WARN"} &nbsp; Redesign image ${selectedGeneration ? (selectedGeneration.is_stale ? "is outdated" : selectedGeneration.is_approved ? "is approved" : "is an unapproved AI preview") : "is missing; the report will show a placeholder"}</li>
            ${missingCount ? `<li class="report-warning">WARN &nbsp; ${missingCount} regions have no measurement (excluded from totals)</li>` : '<li class="report-ready">OK &nbsp; All selected regions have measurements</li>'}
            ${aiCount ? `<li class="report-warning">WARN &nbsp; ${aiCount} measurements are AI estimates</li>` : ""}
            ${hasDefaultRates ? '<li class="report-info">INFO &nbsp; Default placeholder rates are used</li>' : ""}
          </ul>
          <button id="report-create" class="btn btn-primary" type="button"
            ${noPhoto || noSelections || this.busy ? "disabled" : ""}>
            ${this.busy ? "Preparing your report..." : "Generate PDF report"}
          </button>
        </section>

        <section class="card report-history">
          <h3>Previous reports</h3>
          ${(this.ctx.store.getState("reports") || []).length ? `
            <div class="report-history-list">
              ${(this.ctx.store.getState("reports") || []).map((report) => {
                const reportVariant = variants.find((item) => item.id === report.variant_id);
                return `<div class="report-history-row">
                  <span>${this.escape(this.ctx.ui.formatDate(report.created_at))}</span>
                  <span>${this.escape(reportVariant?.name || "Deleted design")}</span>
                  <span>${this.escape(this.ctx.ui.formatCurrency(report.grand_total, report.currency))}</span>
                  <a class="btn btn-secondary btn-small" href="${this.ctx.api.getReportDownloadUrl(this.ctx.projectId, report.id)}">Download</a>
                </div>`;
              }).join("")}
            </div>` : '<p class="text-muted">No reports have been generated yet.</p>'}
        </section>
        <div class="screen-nav">
          <button id="report-back" class="btn btn-secondary" type="button">&larr; Back to Estimates</button>
        </div>
      </div>`;

    this.container.querySelector("#report-variant")?.addEventListener("change", (event) => {
      this.changeVariant(event.target.value);
    });
    this.container.querySelector("#report-generation")?.addEventListener("change", (event) => {
      this.selectedGenerationId = event.target.value || null;
      this.generationWasChanged = true;
      this.render();
    });
    this.container.querySelector("#report-create")?.addEventListener("click", () => this.createReport());
    this.container.querySelector("#report-retry-create")?.addEventListener("click", () => this.createReport());
    this.container.querySelector("#report-back")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/estimate`);
    });
    this.container.querySelector("#report-go-prerequisite")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/${noPhoto ? "upload" : "materials"}`);
    });
  },

  async changeVariant(variantId) {
    try {
      const project = await this.ctx.api.updateProject(this.ctx.projectId, {
        active_variant_id: variantId,
      });
      this.ctx.store.setState("project", project);
      this.ctx.store.setState("activeVariantId", project.active_variant_id);
      this.generationWasChanged = false;
      await this.refreshVariantData(variantId);
      await this.render();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async createReport() {
    if (this.busy) return;
    this.busy = true;
    this.actionError = null;
    await this.render();
    this.ctx.ui.showBusy("Preparing your report...");
    try {
      const project = this.ctx.store.getState("project");
      const variantId = project?.active_variant_id || this.ctx.store.getState("activeVariantId");
      const data = { variant_id: variantId };
      if (this.generationWasChanged && this.selectedGenerationId) {
        data.generation_id = this.selectedGenerationId;
      }
      const report = await this.ctx.api.createReport(this.ctx.projectId, data);
      this.actionError = null;
      await this.ctx.store.refreshReports(this.ctx.projectId);
      await this.render();
      const link = document.createElement("a");
      link.href = report.download_url;
      link.download = "";
      link.hidden = true;
      document.body.appendChild(link);
      link.click();
      link.remove();
      this.ctx.ui.showToast("Your PDF report is ready.", "success");
    } catch (error) {
      const message = error.code === "INTERNAL_ERROR"
        ? "We could not create the report. Please try again."
        : error.message;
      if (error.code === "INTERNAL_ERROR") this.actionError = message;
      this.ctx.ui.showToast(message, "error", 6000, error.requestId);
      if (error.code === "NO_PHOTO" || error.code === "NO_SELECTIONS") {
        this.loading = true;
        this.actionError = null;
        await this.load();
        return;
      }
      if (this.active) await this.render();
    } finally {
      this.ctx.ui.hideBusy();
      this.busy = false;
      if (this.active) await this.render();
    }
  },

  generationLabel(generation) {
    const date = this.ctx.ui.formatDate(generation.created_at);
    const status = generation.is_stale
      ? "Outdated"
      : generation.is_approved ? "Approved" : "Not approved";
    return `${status} - ${date}`;
  },

  escape(value) {
    return this.ctx.ui.escapeHtml(String(value ?? ""));
  },

  unmount() {
    this.active = false;
    this.container.innerHTML = "";
  },
};
