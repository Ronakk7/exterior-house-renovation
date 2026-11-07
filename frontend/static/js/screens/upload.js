/**
 * Step 1: Photo Upload screen.
 */

export const uploadScreen = {
  async mount(container, ctx) {
    this.container = container;
    this.ctx = ctx;
    this.active = true;
    this.error = null;
    this.loadFailed = false;
    this.uploading = false;
    try {
      const result = await this.ctx.api.listPhotos(this.ctx.projectId);
      if (this.active && this.ctx.store.getState("project")?.id === this.ctx.projectId) {
        this.ctx.store.setState("photos", result.items || []);
      }
    } catch (error) {
      this.error = error;
      this.loadFailed = true;
      this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
    }
    await this.render();
  },

  async render() {
    if (!this.active) return;
    const config = this.ctx.store.getState("config") || {};
    const uploadConfig = config.upload || {};
    const photos = this.ctx.store.getState("photos") || [];
    const photo = photos[0] || null;
    const acceptedTypes = uploadConfig.allowed_mime_types || [];
    const maxMb = uploadConfig.max_upload_mb || 10;

    this.container.innerHTML = `
      <div class="screen-view">
        <div class="mb-lg">
          <h2>Step 1: Upload House Image</h2>
          <p class="text-muted">Upload a clear exterior photograph or 3D architectural rendering of your house.</p>
        </div>

        <div class="upload-layout">
          <section class="card upload-card" aria-label="House exterior image">
            ${
              this.loadFailed
                ? `
                  <p class="upload-error" role="alert">
                    Could not load this project's image. ${this.ctx.ui.escapeHtml(this.error?.message || "")}
                  </p>
                  <button id="btn-retry-photos" class="btn btn-secondary" type="button">Retry</button>
                `
                : photo
                ? `
                  <img class="upload-preview" src="${this.ctx.ui.escapeHtml(photo.image_url)}?v=${encodeURIComponent(photo.id)}"
                    alt="Original house exterior image">
                  <p class="upload-photo-meta">
                    ${this.ctx.ui.escapeHtml(photo.original_filename)}
                    &middot; ${photo.width_px} &times; ${photo.height_px} px
                  </p>
                  <button id="btn-replace-photo" class="btn btn-secondary" type="button">Replace image</button>
                `
                : `
                  <div class="upload-dropzone ${this.uploading ? "upload-dropzone--disabled" : ""}" id="upload-dropzone" tabindex="0" role="button"
                    aria-label="Choose or drop a house exterior image">
                    <div class="upload-icon" aria-hidden="true">🏠</div>
                    <h3>Upload Exterior Image</h3>
                    <p class="text-muted">
                      Upload a clear exterior photograph or 3D architectural rendering of your house.
                      Accepted formats: JPG, PNG or WebP; up to ${maxMb} MB.
                    </p>
                    <label class="btn btn-primary" for="photo-file">Choose an image</label>
                    <input id="photo-file" class="sr-only" type="file"
                      accept="${this.ctx.ui.escapeHtml(acceptedTypes.join(","))}" ${this.uploading ? "disabled" : ""}>
                  </div>
                  <div id="upload-progress" class="upload-progress hidden" aria-live="polite">
                    <label for="upload-progress-bar">Uploading image: <span id="upload-progress-value">0%</span></label>
                    <progress id="upload-progress-bar" max="100" value="0">0%</progress>
                  </div>
                  <p class="upload-error ${this.error ? "" : "hidden"}" id="upload-error" role="alert">
                    ${this.error ? this.ctx.ui.escapeHtml(this.error.message) : ""}
                    ${
                      this.error?.requestId
                        ? `<small>Reference: ${this.ctx.ui.escapeHtml(this.error.requestId)}</small>`
                        : ""
                    }
                    ${
                      this.error?.code === "UPLOAD_INVALID_TYPE"
                        ? '<small>iPhone users: choose “Most Compatible” camera format or export as JPG.</small>'
                        : ""
                    }
                    ${this.error ? '<button id="btn-choose-again" class="btn btn-secondary btn-sm" type="button">Choose another image</button>' : ""}
                  </p>
                `
            }
          </section>

          <aside class="card upload-guidance">
            <h3>Image guidance</h3>
            <ul>
              <li>Use a clear exterior image that shows the whole house from the front; a photograph or a 3D architectural rendering is supported.</li>
              <li>For photographs, use daylight and keep the camera level; avoid strong angles.</li>
              <li>Avoid large obstructions such as vehicles, trees or people.</li>
              <li>Include one side of the house per image.</li>
            </ul>
            <p class="privacy-note">
              Your image is sent to Google's Gemini service to analyse it and create the redesign.
              Do not upload images you are not comfortable sharing.
            </p>
          </aside>
        </div>

        <div class="screen-nav">
          <button id="btn-back" class="btn btn-secondary" type="button">&larr; All Projects</button>
          ${
            photo
              ? '<button id="btn-next" class="btn btn-primary" type="button">Continue to Components &rarr;</button>'
              : '<span></span>'
          }
        </div>
      </div>
    `;

    this.container.querySelector("#btn-back").addEventListener("click", () => {
      this.ctx.router.navigate("#/");
    });

    this.container.querySelector("#btn-next")?.addEventListener("click", () => {
      this.ctx.router.navigate(`#/p/${this.ctx.projectId}/components`);
    });

    this.container.querySelector("#btn-retry-photos")?.addEventListener("click", async () => {
      try {
        const result = await this.ctx.api.listPhotos(this.ctx.projectId);
        if (this.active && this.ctx.store.getState("project")?.id === this.ctx.projectId) {
          this.ctx.store.setState("photos", result.items || []);
          this.error = null;
          this.loadFailed = false;
          await this.render();
        }
      } catch (error) {
        this.error = error;
        if (this.active) {
          this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
        }
      }
    });

    this.container.querySelector("#btn-replace-photo")?.addEventListener("click", () => {
      this.replacePhoto(photo);
    });

    const input = this.container.querySelector("#photo-file");
    const dropzone = this.container.querySelector("#upload-dropzone");
    this.container.querySelector("#btn-choose-again")?.addEventListener("click", () => {
      input?.click();
    });
    input?.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      input.value = "";
      await this.handleFiles(files);
    });
    dropzone?.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropzone.classList.add("upload-dropzone--active");
    });
    dropzone?.addEventListener("dragleave", () => {
      dropzone.classList.remove("upload-dropzone--active");
    });
    dropzone?.addEventListener("drop", async (event) => {
      event.preventDefault();
      dropzone.classList.remove("upload-dropzone--active");
      await this.handleFiles(Array.from(event.dataTransfer?.files || []));
    });
    dropzone?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input?.click();
      }
    });
  },

  async replacePhoto(photo) {
    const confirmed = await this.ctx.ui.confirmModal(
      "Replace image",
      "Replacing the image removes its detected regions, material choices and designs."
    );
    if (!confirmed) return;

    try {
      await this.ctx.api.deletePhoto(this.ctx.projectId, photo.id);
      if (!this.active) return;
      this.ctx.store.setState("photos", []);
      this.error = null;
      await this.render();
      const project = await this.ctx.api.getProject(this.ctx.projectId);
      if (this.ctx.store.getState("project")?.id === this.ctx.projectId) {
        this.ctx.store.setState("project", project);
      }
    } catch (error) {
      if (this.active) {
        this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      }
    }
  },

  async handleFiles(files) {
    if (!files.length || this.uploading) return;
    if (files.length > 1) {
      this.ctx.ui.showToast("Only one image is used per project.", "warning");
    }
    const file = files[0];
    this.error = null;

    try {
      await this.precheck(file);
      await this.upload(file);
    } catch (error) {
      if (this.active) {
        this.error = error;
        await this.render();
        this.ctx.ui.showToast(error.message, "error", 6000, error.requestId);
      }
    }
  },

  async precheck(file) {
    const uploadConfig = this.ctx.store.getState("config")?.upload || {};
    const allowedTypes = uploadConfig.allowed_mime_types || [];
    if (!allowedTypes.includes(file.type)) {
      const error = new Error("This file type is not supported. Please upload a JPG, PNG or WebP image.");
      error.code = "UPLOAD_INVALID_TYPE";
      throw error;
    }
    if (file.size > (uploadConfig.max_upload_mb || 10) * 1024 * 1024) {
      const error = new Error(`This image is too large. Please upload a file under ${uploadConfig.max_upload_mb || 10} MB.`);
      error.code = "UPLOAD_TOO_LARGE";
      throw error;
    }

    const objectUrl = URL.createObjectURL(file);
    try {
      const dimensions = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve({
          width: image.naturalWidth,
          height: image.naturalHeight,
        });
        image.onerror = () => reject(new Error("We could not read this image. Please try a different one."));
        image.src = objectUrl;
      });
      if (Math.min(dimensions.width, dimensions.height) < (uploadConfig.min_short_side_px || 600)) {
        const error = new Error(
          `This image is too small (${dimensions.width} x ${dimensions.height}). Please upload one at least ${uploadConfig.min_short_side_px || 600} pixels on its shorter side.`
        );
        error.code = "UPLOAD_TOO_SMALL";
        throw error;
      }
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  },

  async upload(file) {
    this.uploading = true;
    await this.render();
    const progress = this.container.querySelector("#upload-progress");
    const progressBar = this.container.querySelector("#upload-progress-bar");
    const progressValue = this.container.querySelector("#upload-progress-value");
    progress?.classList.remove("hidden");

    try {
      const photo = await this.ctx.api.uploadPhoto(
        this.ctx.projectId,
        file,
        (percent) => {
          if (!this.active) return;
          if (progressBar) progressBar.value = percent;
          if (progressValue) progressValue.textContent = `${percent}%`;
        }
      );
      if (this.ctx.store.getState("project")?.id === this.ctx.projectId) {
        this.ctx.store.setState("photos", [photo]);
      }
      try {
        const project = await this.ctx.api.updateProject(this.ctx.projectId, {
          last_step: "components",
        });
        if (this.ctx.store.getState("project")?.id === this.ctx.projectId) {
          this.ctx.store.setState("project", project);
        }
      } catch (error) {
        if (this.active) {
          this.ctx.ui.showToast(
            "Photo uploaded, but the project resume step could not be updated.",
            "error",
            6000,
            error.requestId
          );
        }
      }
      this.error = null;
    } finally {
      this.uploading = false;
    }
    if (this.active) await this.render();
  },

  unmount() {
    this.active = false;
    this.container.innerHTML = "";
  },
};
