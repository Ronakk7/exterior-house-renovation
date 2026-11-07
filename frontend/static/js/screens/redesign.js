/**
 * Step 4: AI redesign generation, comparison, approval, and history.
 */

import { renderStepper } from "../stepper.js";

export const redesignScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.loading = true;
    this.loadError = null;
    this.actionError = null;
    this.selectedGenerationId = null;
    this.extraInstructions = "";
    this.sliderValue = 50;
    this.comparisonMode = "slider";
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
      if (!this.ctx.store.getState("catalogue")) {
        this.ctx.store.setState("catalogue", await this.ctx.api.getCatalogue());
      }
      if (!this.active) return;
      await this.ctx.store.refreshGenerations(
        this.ctx.projectId,
        project.active_variant_id
      );
      const generations = this.generations();
      if (!generations.some((item) => item.id === this.selectedGenerationId)) {
        this.selectedGenerationId = generations.find((item) => item.status === "succeeded")?.id
          || generations[0]?.id
          || null;
      }
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
      this.container.innerHTML = '<div class="loading-state" role="status">Loading redesigns...</div>';
      return;
    }
    if (this.loadError) {
      this.container.innerHTML = `
        <section class="card detection-error" role="alert">
          <h2>Could not load redesigns</h2>
          <p>${this.ctx.ui.escapeHtml(this.loadError.message)}</p>
          <button id="redesign-retry-load" class="btn btn-primary" type="button">Retry</button>
        </section>`;
      this.container.querySelector("#redesign-retry-load").addEventListener("click", () => {
        this.loading = true;
        this.loadError = null;
        this.load();
      });
      return;
    }
    const project = this.ctx.store.getState("project");
    const photo = (this.ctx.store.getState("photos") || [])[0];
    const components = this.ctx.store.getState("components") || [];
    const variants = this.ctx.store.getState("variants") || [];
    const activeId = project?.active_variant_id || this.ctx.store.getState("activeVariantId");
    const variant = variants.find((item) => item.id === activeId) || variants[0];
    const selectedCount = variant?.selections?.length || 0;
    const generations = this.generations();
    const selected = generations.find((item) => item.id === this.selectedGenerationId) || null;
    const prerequisites = !photo
      ? "Upload a photo before generating a redesign."
      : components.length === 0
        ? "Detect or add regions before generating a redesign."
        : selectedCount === 0
          ? "Choose at least one material before generating a redesign."
          : null;

    this.container.innerHTML = `
      <div class="screen-view">
        <header class="mb-lg">
          <h2>Step 4: AI Visual Redesign</h2>
          <p class="text-muted">Create a preview using your selections. Compare it carefully with the original house.</p>
        </header>
        ${prerequisites ? `
          <section class="prerequisite-panel">
            <p>${this.ctx.ui.escapeHtml(prerequisites)}</p>
            <button id="redesign-go-prerequisite" class="btn btn-primary" type="button">
              Go to ${!photo ? "Upload" : components.length === 0 ? "Components" : "Materials"}
            </button>
          </section>` : `
          <section class="redesign-toolbar card">
            <label for="redesign-variant">Design</label>
            <select id="redesign-variant">
              ${variants.map((item) => `
                <option value="${this.ctx.ui.escapeHtml(item.id)}" ${item.id === variant?.id ? "selected" : ""}>
                  ${this.ctx.ui.escapeHtml(item.name)}
                </option>`).join("")}
            </select>
            <p class="selection-chip-list">
              ${this.selectionSummary(variant)}
            </p>
          </section>
          <form id="generation-form" class="generation-form card">
            <label for="extra-instructions">Additional preferences for the selected areas (optional)</label>
            <textarea id="extra-instructions" maxlength="500" rows="3"
              placeholder="Make the selected wall finish a little darker and give the facade a warm, premium appearance.">${this.ctx.ui.escapeHtml(this.extraInstructions)}</textarea>
            <p class="text-muted">Describe how the selected areas should look. These preferences refine the materials you selected. They do not change unselected regions or the house structure.</p>
            <div class="generation-form__footer">
              <span id="instruction-counter">${this.extraInstructions.length}/500</span>
              <button id="generate-redesign" class="btn btn-primary" type="submit">
                ${generations.length ? "Generate again" : "Generate redesign"}
              </button>
            </div>
          </form>
          ${this.renderActionError()}
          ${this.renderGeneration(selected, photo)}
          ${this.renderHistory(generations)}
        `}
        <nav class="screen-nav" aria-label="Screen navigation">
          <button id="btn-back" class="btn btn-secondary" type="button">&larr; Back to Materials</button>
          <button id="btn-next" class="btn btn-secondary" type="button">Next: Estimate costs &rarr;</button>
        </nav>
      </div>`;

    this.bindNavigation();
    this.container.querySelector("#redesign-go-prerequisite")?.addEventListener("click", () => {
      const step = !photo ? "upload" : components.length === 0 ? "components" : "materials";
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/${step}`);
    });
    this.container.querySelector("#redesign-variant")?.addEventListener("change", (event) => {
      this.switchVariant(event.target.value);
    });
    const instructions = this.container.querySelector("#extra-instructions");
    instructions?.addEventListener("input", (event) => {
      this.extraInstructions = event.target.value.slice(0, 500);
      const counter = this.container.querySelector("#instruction-counter");
      if (counter) counter.textContent = `${this.extraInstructions.length}/500`;
    });
    this.container.querySelector("#generation-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.generate(photo, variant);
    });
    this.container.querySelector("#retry-generation")?.addEventListener("click", () => {
      this.generate(photo, variant);
    });
    this.container.querySelector("#comparison-mode")?.addEventListener("change", (event) => {
      this.comparisonMode = event.target.value;
      this.render();
    });
    this.container.querySelector("#comparison-slider")?.addEventListener("input", (event) => {
      this.sliderValue = Number(event.target.value);
      const overlay = this.container.querySelector(".comparison-generated");
      if (overlay) overlay.style.clipPath = `inset(0 ${100 - this.sliderValue}% 0 0)`;
      const label = this.container.querySelector("#comparison-value");
      if (label) label.textContent = `${this.sliderValue}% redesigned`;
    });
    this.container.querySelector("#approve-generation")?.addEventListener("click", () => {
      this.toggleApproval(selected);
    });
    this.container.querySelector("#view-prompt")?.addEventListener("click", () => {
      this.viewPrompt(selected);
    });
    this.container.querySelector("#delete-generation")?.addEventListener("click", () => {
      this.removeGeneration(selected);
    });
    this.container.querySelectorAll("[data-generation-id]").forEach((button) => {
      button.addEventListener("click", () => {
        this.selectedGenerationId = button.dataset.generationId;
        this.render();
      });
    });
    this.container.querySelectorAll("[data-delete-generation-id]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const generation = generations.find((item) => item.id === button.dataset.deleteGenerationId);
        this.removeGeneration(generation);
      });
    });
    this.updateStepper();
  },

  renderActionError() {
    if (!this.actionError) return "";
    const error = this.actionError;
    const persistent = error.code === "AI_NOT_CONFIGURED";
    return `
      <section class="redesign-error ${persistent ? "redesign-error--persistent" : ""}" role="alert">
        ${persistent ? "<strong>AI features are not configured on this server.</strong>" : ""}
        <p>${this.ctx.ui.escapeHtml(error.message)}</p>
        ${!persistent ? '<button id="retry-generation" class="btn btn-secondary" type="button">Try again</button>' : ""}
      </section>`;
  },

  renderGeneration(generation, photo) {
    if (!generation) {
      return `<section class="card redesign-empty" role="status">
        <p>No redesign has been generated for this design yet.</p>
      </section>`;
    }
    if (generation.status !== "succeeded") {
      return `
        <section class="card generation-failed" role="alert">
          <h3>Redesign ${this.ctx.ui.escapeHtml(generation.status)}</h3>
          <p>${this.ctx.ui.escapeHtml(generation.error_message || "This generation did not produce an image.")}</p>
          <button id="delete-generation" class="btn btn-danger" type="button">Delete</button>
        </section>`;
    }
    const originalUrl = photo?.image_url || "";
    const generatedUrl = `${generation.image_url}?v=${encodeURIComponent(generation.id)}`;
    const stale = generation.is_stale;
    const comparison = this.comparisonMode === "side-by-side"
      ? `<div class="comparison-side-by-side">
          <figure><img src="${this.ctx.ui.escapeHtml(originalUrl)}" alt="Original house photo"><figcaption>Original photo</figcaption></figure>
          <figure><img src="${this.ctx.ui.escapeHtml(generatedUrl)}" alt="Redesigned house, AI-generated">
            <span class="badge badge--ai-generated">AI-generated image</span><figcaption>Redesign preview</figcaption></figure>
        </div>`
      : `<div class="comparison-stage">
          <img class="comparison-original" src="${this.ctx.ui.escapeHtml(originalUrl)}" alt="Original house photo">
          <div class="comparison-generated" style="clip-path:inset(0 ${100 - this.sliderValue}% 0 0)">
            <img src="${this.ctx.ui.escapeHtml(generatedUrl)}" alt="Redesigned house, AI-generated">
            <span class="badge badge--ai-generated">AI-generated image</span>
          </div>
          <span class="comparison-divider" style="left:${this.sliderValue}%"></span>
        </div>
        <label class="comparison-slider-label" for="comparison-slider">
          Compare original and redesign <span id="comparison-value">${this.sliderValue}% redesigned</span>
        </label>
        <input id="comparison-slider" type="range" min="0" max="100" value="${this.sliderValue}" aria-label="Move comparison divider">`;
    return `
      <section class="card redesign-result">
        <header class="redesign-result__header">
          <div>
            <h3>Redesign preview</h3>
            ${stale ? '<span class="badge badge--outdated">Outdated</span>' : ""}
            ${generation.is_approved ? '<span class="badge badge--supported">Approved</span>' : ""}
          </div>
          <label for="comparison-mode">View</label>
          <select id="comparison-mode">
            <option value="slider" ${this.comparisonMode === "slider" ? "selected" : ""}>Slider</option>
            <option value="side-by-side" ${this.comparisonMode === "side-by-side" ? "selected" : ""}>Side by side</option>
          </select>
        </header>
        ${stale ? '<p class="redesign-stale-banner" role="status">Your materials or regions changed since this image was created. Generate again to update it.</p>' : ""}
        ${comparison}
        <p class="ai-preview-warning">This is an AI-generated preview. Colours, textures and details can differ from real materials, and small details of your house may change. Check that the structure matches your house before approving.</p>
        <div class="generation-actions">
          <button id="approve-generation" class="btn btn-primary" type="button">
            ${generation.is_approved ? "Unapprove" : "Approve"}
          </button>
          <a class="btn btn-secondary" href="${this.ctx.ui.escapeHtml(generation.image_url)}"
            download="renovation-preview-${this.ctx.ui.escapeHtml(generation.id)}.png">Download image</a>
          <button id="view-prompt" class="btn btn-secondary" type="button">View prompt</button>
          <button id="delete-generation" class="btn btn-danger" type="button">Delete</button>
        </div>
      </section>`;
  },

  renderHistory(generations) {
    if (!generations.length) return "";
    return `
      <section class="card generation-history">
        <h3>History (this design)</h3>
        <ul class="generation-history__list">
          ${generations.slice(0, 20).map((generation) => `
            <li>
              <button class="generation-history__item ${generation.id === this.selectedGenerationId ? "generation-history__item--selected" : ""}"
                data-generation-id="${this.ctx.ui.escapeHtml(generation.id)}" type="button">
                ${generation.image_url ? `
                  <img src="${this.ctx.ui.escapeHtml(generation.image_url)}?v=${encodeURIComponent(generation.id)}"
                    alt="AI-generated redesign thumbnail">` : '<span class="generation-history__placeholder">No image</span>'}
                <span>${this.ctx.ui.escapeHtml(this.ctx.ui.formatDate(generation.created_at))}</span>
                <span class="generation-history__badges">
                  ${generation.is_approved ? '<span class="badge badge--supported">Approved</span>' : ""}
                  ${generation.is_stale ? '<span class="badge badge--outdated">Outdated</span>' : ""}
                  ${generation.status === "failed" ? '<span class="badge badge--approximate">Failed</span>' : ""}
                </span>
                ${generation.status === "failed" ? `<span class="generation-history__error">${this.ctx.ui.escapeHtml(generation.error_message || "Generation failed.")}</span>` : ""}
              </button>
              ${generation.status === "failed" ? `<button class="btn btn-danger" data-delete-generation-id="${this.ctx.ui.escapeHtml(generation.id)}" type="button">Delete</button>` : ""}
            </li>`).join("")}
        </ul>
      </section>`;
  },

  selectionSummary(variant) {
    const catalogue = this.ctx.store.getState("catalogue");
    const materials = new Map((catalogue?.materials || []).map((item) => [item.id, item]));
    const components = new Map(this.ctx.store.getState("components").map((item) => [item.id, item]));
    return (variant?.selections || []).map((selection) => {
      const component = components.get(selection.component_id);
      const material = materials.get(selection.material_id);
      return component && material
        ? `<span class="selection-chip">${this.ctx.ui.escapeHtml(typeLabel(component.type))}: ${this.ctx.ui.escapeHtml(material.name)}</span>`
        : "";
    }).join("") || '<span class="text-muted">No material selections</span>';
  },

  async generate(photo, variant) {
    if (!photo || !variant) return;
    this.actionError = null;
    const button = this.container.querySelector("#generate-redesign");
    if (button) button.disabled = true;
    this.ctx.ui.showBusy("Creating your redesign...");
    try {
      const generation = await this.ctx.api.createGeneration(
        this.ctx.projectId,
        variant.id,
        {
          photo_id: photo.id,
          extra_instructions: this.extraInstructions.trim() || null,
        }
      );
      if (!this.active) return;
      this.selectedGenerationId = generation.id;
      await this.ctx.store.refreshGenerations(this.ctx.projectId, variant.id);
      this.ctx.ui.showToast("Redesign created.", "success");
    } catch (error) {
      if (!this.active) return;
      this.actionError = error;
      const generationId = error.details?.generation_id;
      if (generationId) this.selectedGenerationId = generationId;
      this.ctx.ui.showToast(
        error.message,
        ["AI_CONTENT_BLOCKED", "AI_RATE_LIMITED"].includes(error.code) ? "warning" : "error",
        error.code === "AI_NOT_CONFIGURED" ? 0 : 6000,
        error.requestId
      );
      try {
        await this.ctx.store.refreshGenerations(this.ctx.projectId, variant.id);
      } catch (refreshError) {
        this.ctx.ui.showToast(refreshError.message, "error", 6000, refreshError.requestId);
      }
    } finally {
      this.ctx.ui.hideBusy();
      if (this.active) await this.render();
    }
  },

  async toggleApproval(generation) {
    if (!generation || generation.status !== "succeeded") return;
    if (!generation.is_approved && generation.is_stale) {
      const accepted = await this.ctx.ui.confirmModal(
        "Approve outdated preview?",
        "This image no longer matches the current materials or regions. Approve it anyway?"
      );
      if (!accepted) return;
    }
    try {
      await this.ctx.api.approveGeneration(this.ctx.projectId, generation.id, {
        is_approved: !generation.is_approved,
      });
      await this.ctx.store.refreshGenerations(this.ctx.projectId, generation.variant_id);
      this.ctx.ui.showToast(generation.is_approved ? "Approval removed." : "Redesign approved.", "success");
      await this.render();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async viewPrompt(generation) {
    if (!generation) return;
    try {
      const detail = await this.ctx.api.getGeneration(this.ctx.projectId, generation.id);
      const dialog = document.createElement("dialog");
      dialog.className = "prompt-dialog";
      dialog.innerHTML = `
        <form method="dialog">
          <h2>Redesign prompt</h2>
          <pre></pre>
          <button class="btn btn-primary" type="submit">Close</button>
        </form>`;
      dialog.querySelector("pre").textContent = detail.prompt_text;
      document.body.appendChild(dialog);
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      dialog.showModal();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async removeGeneration(generation) {
    if (!generation) return;
    const accepted = await this.ctx.ui.confirmModal(
      "Delete redesign?",
      "This permanently deletes this generated preview."
    );
    if (!accepted) return;
    try {
      await this.ctx.api.deleteGeneration(this.ctx.projectId, generation.id);
      this.selectedGenerationId = null;
      await this.ctx.store.refreshGenerations(this.ctx.projectId, generation.variant_id);
      await this.render();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  async switchVariant(variantId) {
    try {
      const project = await this.ctx.api.updateProject(this.ctx.projectId, {
        active_variant_id: variantId,
      });
      this.ctx.store.setState("project", project);
      this.ctx.store.setState("activeVariantId", project.active_variant_id);
      await Promise.all([
        this.ctx.store.refreshVariants(this.ctx.projectId),
        this.ctx.store.refreshGenerations(this.ctx.projectId, variantId),
      ]);
      this.selectedGenerationId = null;
      await this.render();
    } catch (error) {
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
  },

  bindNavigation() {
    this.container.querySelector("#btn-back")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/materials`);
    });
    this.container.querySelector("#btn-next")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/estimate`);
    });
  },

  updateStepper() {
    renderStepper(
      document.getElementById("workflow-stepper"),
      "redesign",
      this.ctx.projectId,
      this.ctx.store
    );
  },

  generations() {
    return this.ctx.store.getState("generations") || [];
  },

  unmount() {
    this.active = false;
    this.container.innerHTML = "";
  },
};

function typeLabel(value) {
  return value.replaceAll("_", " ");
}
