/**
 * Project list, creation, rename, and deletion screen.
 */

const PAGE_SIZE = 50;
const STEP_LABELS = {
  upload: "Upload",
  components: "Components",
  materials: "Materials",
  redesign: "Redesign",
  estimate: "Estimate",
  report: "Report",
};

export const projectsScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.projects = [];
    this.total = 0;
    this.loading = false;
    this.container.innerHTML = `
      <div class="projects-view">
        <div class="flex-between mb-lg">
          <div>
            <h1>Exterior Renovation Projects</h1>
            <p class="text-muted">Plan exterior upgrades, preview redesigns, and compute costs.</p>
          </div>
          <button id="btn-new-project" class="btn btn-primary" type="button">+ New project</button>
        </div>
        <div id="projects-list-container">
          <div class="loading-state">Loading your projects...</div>
        </div>
        <div id="create-project-modal" class="modal-backdrop hidden" role="dialog" aria-modal="true"
          aria-labelledby="create-project-title">
          <form id="create-project-form" class="modal-dialog">
            <h2 id="create-project-title" class="modal-title">Create a project</h2>
            <label class="form-label" for="new-project-name">Project name</label>
            <input id="new-project-name" class="form-input" name="name" maxlength="100"
              value="My house" required autocomplete="off">
            <p id="create-project-error" class="form-error hidden" role="alert"></p>
            <div class="modal-actions">
              <button id="btn-cancel-create" class="btn btn-secondary" type="button">Cancel</button>
              <button class="btn btn-primary" type="submit">Create project</button>
            </div>
          </form>
        </div>
      </div>
    `;

    this.container.querySelector("#btn-new-project").addEventListener("click", () => {
      this.openCreateModal();
    });
    this.container.querySelector("#btn-cancel-create").addEventListener("click", () => {
      this.closeCreateModal();
    });
    this.container.querySelector("#create-project-form").addEventListener("submit", (event) => {
      event.preventDefault();
      this.handleCreateProject();
    });
    const modal = this.container.querySelector("#create-project-modal");
    modal.addEventListener("click", (event) => {
      if (event.target === modal) this.closeCreateModal();
    });
    modal.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        modal.querySelectorAll("input:not(:disabled), button:not(:disabled)")
      );
      if (!focusable.length) return;
      if (event.shiftKey && document.activeElement === focusable[0]) {
        event.preventDefault();
        focusable.at(-1).focus();
      } else if (!event.shiftKey && document.activeElement === focusable.at(-1)) {
        event.preventDefault();
        focusable[0].focus();
      }
    });
    this.escapeHandler = (event) => {
      if (event.key === "Escape") this.closeCreateModal();
    };
    window.addEventListener("keydown", this.escapeHandler);

    await this.loadProjects(true);
  },

  openCreateModal() {
    const modal = this.container.querySelector("#create-project-modal");
    modal.classList.remove("hidden");
    this.container.querySelector("#new-project-name").focus();
  },

  closeCreateModal() {
    this.container.querySelector("#create-project-modal")?.classList.add("hidden");
  },

  async loadProjects(reset = false) {
    const listEl = this.container.querySelector("#projects-list-container");
    if (!listEl || this.loading) return;
    this.loading = true;
    if (reset) {
      this.projects = [];
      listEl.innerHTML = '<div class="loading-state">Loading your projects...</div>';
    }

    try {
      const offset = this.projects.length;
      const data = await this.ctx.api.listProjects(PAGE_SIZE, offset);
      if (!this.active) return;
      this.projects = reset
        ? data.items || []
        : this.projects.concat(data.items || []);
      this.total = data.total || 0;
      this.renderProjects();
    } catch (error) {
      if (!this.active) return;
      listEl.innerHTML = `
        <div class="card text-center text-error">
          <p>Could not load projects. ${this.ctx.ui.escapeHtml(error.message)}</p>
          <button id="btn-retry-list" class="btn btn-secondary" type="button">Retry</button>
        </div>
      `;
      listEl.querySelector("#btn-retry-list").addEventListener("click", () => {
        this.loadProjects(true);
      });
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.loading = false;
    }
  },

  renderProjects() {
    const listEl = this.container.querySelector("#projects-list-container");
    if (!this.projects.length) {
      listEl.innerHTML = `
        <div class="card text-center" style="padding: 48px 24px;">
          <div style="font-size: 48px; margin-bottom: 16px;" aria-hidden="true">🏡</div>
          <h2>No projects yet. Create one to start.</h2>
          <button id="btn-create-first" class="btn btn-primary" type="button">New project</button>
        </div>
      `;
      listEl.querySelector("#btn-create-first").addEventListener("click", () => {
        this.openCreateModal();
      });
      return;
    }

    listEl.innerHTML = `
      <div class="projects-grid">
        ${this.projects.map((project) => `
          <article class="card project-card" data-id="${this.ctx.ui.escapeHtml(project.id)}">
            <div class="flex-between">
              <h2 class="project-card-title">${this.ctx.ui.escapeHtml(project.name)}</h2>
              <span class="badge">${this.ctx.ui.escapeHtml(STEP_LABELS[project.last_step] || "Upload")}</span>
            </div>
            <form class="project-rename-form hidden" data-id="${this.ctx.ui.escapeHtml(project.id)}">
              <label class="sr-only" for="rename-${this.ctx.ui.escapeHtml(project.id)}">Project name</label>
              <input id="rename-${this.ctx.ui.escapeHtml(project.id)}" class="form-input"
                maxlength="100" value="${this.ctx.ui.escapeHtml(project.name)}" required>
              <div class="project-action-row">
                <button class="btn btn-primary btn-sm" type="submit">Save name</button>
                <button class="btn btn-secondary btn-sm btn-cancel-rename" type="button">Cancel</button>
              </div>
            </form>
            <p class="text-muted project-updated">Updated ${this.ctx.ui.escapeHtml(this.ctx.ui.formatDate(project.updated_at))}</p>
            <p class="text-muted">
              ${project.photo_count} photo${project.photo_count === 1 ? "" : "s"},
              ${project.component_count} regions,
              ${project.variant_count} design${project.variant_count === 1 ? "" : "s"}
            </p>
            <p class="text-muted">Continue: ${this.ctx.ui.escapeHtml(STEP_LABELS[project.last_step] || "Upload")}</p>
            <div class="project-action-row">
              <button class="btn btn-primary btn-sm project-action btn-open-project" data-id="${this.ctx.ui.escapeHtml(project.id)}" type="button">
                Open project
              </button>
              <button class="btn btn-secondary btn-sm project-action btn-rename-project" data-id="${this.ctx.ui.escapeHtml(project.id)}" type="button">
                Rename
              </button>
              <button class="btn btn-secondary btn-sm project-action btn-delete-project text-error" data-id="${this.ctx.ui.escapeHtml(project.id)}" type="button">
                Delete
              </button>
            </div>
          </article>
        `).join("")}
      </div>
      ${
        this.projects.length < this.total
          ? '<div class="text-center mt-lg"><button id="btn-load-more" class="btn btn-secondary" type="button">Load more</button></div>'
          : ""
      }
    `;

    listEl.querySelectorAll(".project-card").forEach((card) => {
      card.addEventListener("click", (event) => {
        if (event.target.closest(".project-action, .project-rename-form")) return;
        this.ctx.router.navigate(`#/p/${card.dataset.id}`);
      });
    });
    listEl.querySelector("#btn-load-more")?.addEventListener("click", () => {
      this.loadProjects(false);
    });
    listEl.querySelectorAll(".btn-open-project").forEach((button) => {
      button.addEventListener("click", () => {
        this.ctx.router.navigate(`#/p/${button.dataset.id}`);
      });
    });
    listEl.querySelectorAll(".btn-rename-project").forEach((button) => {
      button.addEventListener("click", () => {
        const card = button.closest(".project-card");
        const form = card.querySelector(".project-rename-form");
        form.classList.remove("hidden");
        form.querySelector("input").focus();
      });
    });
    listEl.querySelectorAll(".project-rename-form").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const name = form.querySelector("input").value.trim();
        try {
          const updated = await this.ctx.api.updateProject(form.dataset.id, { name });
          this.projects = this.projects.map((project) =>
            project.id === updated.id ? updated : project
          );
          this.renderProjects();
        } catch (error) {
          this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
        }
      });
      form.querySelector(".btn-cancel-rename").addEventListener("click", () => {
        form.classList.add("hidden");
      });
    });
    listEl.querySelectorAll(".btn-delete-project").forEach((button) => {
      button.addEventListener("click", async () => {
        const confirmed = await this.ctx.ui.confirmModal(
          "Delete Project",
          "This permanently deletes the project, its photo, designs and reports."
        );
        if (!confirmed) return;
        try {
          this.ctx.ui.showBusy("Deleting project...");
          await this.ctx.api.deleteProject(button.dataset.id);
          this.ctx.ui.showToast("Project deleted.", "success");
          await this.loadProjects(true);
        } catch (error) {
          this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
        } finally {
          this.ctx.ui.hideBusy();
        }
      });
    });
  },

  async handleCreateProject() {
    const input = this.container.querySelector("#new-project-name");
    const errorEl = this.container.querySelector("#create-project-error");
    const name = input.value.trim();
    if (!name) {
      errorEl.textContent = "Enter a project name.";
      errorEl.classList.remove("hidden");
      input.focus();
      return;
    }

    errorEl.classList.add("hidden");
    try {
      this.ctx.ui.showBusy("Creating project...");
      const created = await this.ctx.api.createProject({ name });
      if (!this.active) return;
      this.ctx.ui.showToast("Project created.", "success");
      this.ctx.router.navigate(`#/p/${created.id}/upload`);
    } catch (error) {
      if (!this.active) return;
      errorEl.textContent = error.message || "Could not create the project.";
      errorEl.classList.remove("hidden");
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    } finally {
      this.ctx.ui.hideBusy();
    }
  },

  unmount() {
    this.active = false;
    window.removeEventListener("keydown", this.escapeHandler);
    this.container.innerHTML = "";
  },
};
