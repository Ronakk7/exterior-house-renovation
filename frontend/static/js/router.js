/**
 * Hash-based Single Page Application Router.
 */

import { renderStepper } from "./stepper.js";

export class Router {
  constructor(routes, container, store, api, ui) {
    this.routes = routes;
    this.container = container;
    this.store = store;
    this.api = api;
    this.ui = ui;
    this.currentScreen = null;

    window.addEventListener("hashchange", () => this.handleRoute());
  }

  init() {
    this.handleRoute();
  }

  async handleRoute() {
    const hash = window.location.hash || "#/";

    // Unmount active screen
    if (this.currentScreen && typeof this.currentScreen.unmount === "function") {
      this.currentScreen.unmount();
      this.currentScreen = null;
    }

    const projectHeader = document.getElementById("project-header-info");
    const headerProjName = document.getElementById("header-project-name");
    const stepperContainer = document.getElementById("stepper-container");
    const stepperEl = document.getElementById("workflow-stepper");

    // Match route
    // 1. Home / projects list
    if (hash === "#/" || hash === "" || hash === "#") {
      if (projectHeader) projectHeader.classList.add("hidden");
      if (stepperContainer) stepperContainer.classList.add("hidden");
      this.store.resetProject();

      const screen = this.routes["#/"];
      if (screen) {
        this.currentScreen = screen;
        await screen.mount(this.container, {
          store: this.store,
          api: this.api,
          ui: this.ui,
          router: this,
          projectId: null,
        });
      }
      return;
    }

    // 2. Project routes: #/p/{projectId}/{step} or #/p/{projectId}
    const match = hash.match(/^#\/p\/([a-zA-Z0-9_-]+)(?:\/([a-zA-Z0-9_-]+))?$/);
    if (!match) {
      this.ui.showToast("Page not found. Redirecting to home...", "warning");
      window.location.hash = "#/";
      return;
    }

    const projectId = match[1];
    let step = match[2];

    try {
      let project = this.store.getState("project");
      if (!project || project.id !== projectId) {
        this.ui.showBusy("Loading project...");
        try {
          project = await this.store.refreshProject(projectId);
        } finally {
          this.ui.hideBusy();
        }
      }

      // If no step provided, redirect to project's last_step
      if (!step) {
        const destStep = project.last_step || "upload";
        window.location.hash = `#/p/${projectId}/${destStep}`;
        return;
      }

      // Update header
      if (projectHeader) projectHeader.classList.remove("hidden");
      if (headerProjName) headerProjName.textContent = project.name;
      if (stepperContainer) stepperContainer.classList.remove("hidden");

      // Render stepper
      renderStepper(stepperEl, step, projectId, this.store);

      // Fire and forget: update last_step on server if step changed
      if (project.last_step !== step) {
        this.api.updateProject(projectId, { last_step: step }).catch(() => {});
        project.last_step = step;
      }

      const screenKey = `#/p/:id/${step}`;
      const screen = this.routes[screenKey];
      if (!screen) {
        this.ui.showToast(`Step '${step}' not found. Redirecting...`, "warning");
        window.location.hash = `#/p/${projectId}/upload`;
        return;
      }

      this.currentScreen = screen;
      await screen.mount(this.container, {
        store: this.store,
        api: this.api,
        ui: this.ui,
        router: this,
        projectId,
        step,
      });
    } catch (err) {
      this.ui.hideBusy();
      if (err.status === 404) {
        this.container.innerHTML = `
          <div class="card text-center" style="margin: 40px auto; max-width: 500px;">
            <h2>Project Not Found</h2>
            <p class="text-muted">The project you are trying to open does not exist or was deleted.</p>
            <a href="#/" class="btn btn-primary mt-md">Back to Projects</a>
          </div>
        `;
      } else {
        this.ui.showToast(err.message || "Failed to load project.", "error");
      }
    }
  }

  navigate(hash) {
    window.location.hash = hash;
  }
}

