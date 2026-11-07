/**
 * Application entry point and bootstrapping.
 */

import * as api from "./api.js";
import { store } from "./store.js";
import * as ui from "./ui.js";
import { Router } from "./router.js";

import { projectsScreen } from "./screens/projects.js";
import { uploadScreen } from "./screens/upload.js";
import { componentsScreen } from "./screens/components.js";
import { materialsScreen } from "./screens/materials.js";
import { redesignScreen } from "./screens/redesign.js";
import { estimateScreen } from "./screens/estimate.js";
import { reportScreen } from "./screens/report.js";

async function bootstrap() {
  const mainContainer = document.getElementById("main-content");

  try {
    // 1. Fetch client config from backend
    const config = await api.getClientConfig();
    store.setState("config", config);

    // 2. Mock mode banner
    const mockBanner = document.getElementById("mock-banner");
    if (mockBanner && config.ai_mock_mode) {
      mockBanner.classList.remove("hidden");
    }

    // 3. Set up routes
    const routes = {
      "#/": projectsScreen,
      "#/p/:id/upload": uploadScreen,
      "#/p/:id/components": componentsScreen,
      "#/p/:id/materials": materialsScreen,
      "#/p/:id/redesign": redesignScreen,
      "#/p/:id/estimate": estimateScreen,
      "#/p/:id/report": reportScreen,
    };

    const router = new Router(routes, mainContainer, store, api, ui);
    router.init();
  } catch (err) {
    if (mainContainer) {
      mainContainer.innerHTML = `
        <div class="card text-center text-error" style="max-width: 500px; margin: 40px auto;">
          <h2>Connection Error</h2>
          <p>Could not initialize application from server.</p>
          <p class="text-muted" style="font-size: 13px;">${ui.escapeHtml(err.message)}</p>
          <button onclick="window.location.reload()" class="btn btn-primary mt-md">Retry</button>
        </div>
      `;
    }
  }

  // Global unhandled error notifications
  window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled promise rejection:", event.reason);
    ui.showToast(
      event.reason?.message || "An unexpected error occurred.",
      "error",
      6000,
      event.reason?.requestId
    );
  });
}

document.addEventListener("DOMContentLoaded", bootstrap);

