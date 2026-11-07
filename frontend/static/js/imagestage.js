/**
 * Image stage helper for rendering and drawing normalized bounding boxes.
 */

export class ImageStage {
  constructor(container, imageUrl, options = {}) {
    this.container = container;
    this.imageUrl = imageUrl;
    this.options = options;
    this.components = [];
    this.selectedId = null;
    this.isDrawing = false;
    this.onDrawnCallback = null;
    this.onDrawTooSmallCallback = null;
    this.onBoxClickCallback = null;
    this.onBoxHoverCallback = null;
    this._gestureCleanup = null;

    this.renderShell();
  }

  renderShell() {
    this.container.innerHTML = `
      <div class="image-stage">
        <img src="${this.imageUrl}" alt="House facade" draggable="false">
        <div class="image-stage__overlay"></div>
      </div>
    `;

    this.stageEl = this.container.querySelector(".image-stage");
    this.overlayEl = this.container.querySelector(".image-stage__overlay");
    this.imgEl = this.container.querySelector("img");

    this.overlayEl.addEventListener("click", (e) => {
      if (this.isDrawing) return;
      const boxEl = e.target.closest(".component-box");
      if (boxEl && this.onBoxClickCallback) {
        const id = boxEl.getAttribute("data-id");
        this.selectBox(id);
        this.onBoxClickCallback(id);
      }
    });
    this.overlayEl.addEventListener("pointerover", (e) => {
      const boxEl = e.target.closest(".component-box");
      this.onBoxHoverCallback?.(boxEl?.getAttribute("data-id") || null);
    });
    this.overlayEl.addEventListener("pointerout", (e) => {
      if (e.target.closest(".component-box")) {
        this.onBoxHoverCallback?.(null);
      }
    });
  }

  renderBoxes(components) {
    this.components = components || [];
    this.overlayEl.innerHTML = "";

    this.components.forEach((cmp) => {
      const box = cmp.box;
      if (!box) return;

      const boxEl = document.createElement("div");
      const isSelected = cmp.id === this.selectedId;
      const isLocked = cmp.is_locked ? "component-box--locked" : "";
      const isUnsupported = !cmp.supported ? "component-box--unsupported" : "";
      const selectedClass = isSelected ? "component-box--selected" : "";

      boxEl.className = `component-box component-box--${cmp.type} ${isLocked} ${isUnsupported} ${selectedClass}`;
      boxEl.setAttribute("data-id", cmp.id);
      boxEl.style.left = `${box.x * 100}%`;
      boxEl.style.top = `${box.y * 100}%`;
      boxEl.style.width = `${box.w * 100}%`;
      boxEl.style.height = `${box.h * 100}%`;

      const typeVar = `var(--color-cmp-${cmp.type}, #3b82f6)`;
      boxEl.style.borderColor = typeVar;

      const labelEl = document.createElement("span");
      labelEl.className = "component-label";
      labelEl.textContent = cmp.label || cmp.type;
      boxEl.appendChild(labelEl);

      this.overlayEl.appendChild(boxEl);
    });
  }

  selectBox(componentId) {
    this.selectedId = componentId;
    this.overlayEl.querySelectorAll(".component-box").forEach((el) => {
      if (el.getAttribute("data-id") === componentId) {
        el.classList.add("component-box--selected");
      } else {
        el.classList.remove("component-box--selected");
      }
    });
  }

  onBoxClick(handler) {
    this.onBoxClickCallback = handler;
  }

  onBoxHover(handler) {
    this.onBoxHoverCallback = handler;
  }

  highlightBox(componentId) {
    this.overlayEl.querySelectorAll(".component-box").forEach((el) => {
      el.classList.toggle(
        "component-box--hovered",
        Boolean(componentId) && el.getAttribute("data-id") === componentId
      );
    });
  }

  enableDrawing(
    onDrawn,
    { allowOnComponents = false, onTooSmall = () => {} } = {}
  ) {
    this.disableDrawing();
    this.onDrawnCallback = onDrawn;
    this.onDrawTooSmallCallback = onTooSmall;
    this.isDrawing = true;
    this.overlayEl.classList.add("image-stage__overlay--drawing");
    let startX = 0;
    let startY = 0;
    let drawBox = null;
    let removeGesture = () => {};

    const onPointerDown = (e) => {
      if (!allowOnComponents && e.target.closest(".component-box")) return;
      e.preventDefault();
      const rect = this.overlayEl.getBoundingClientRect();
      startX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      startY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

      drawBox = document.createElement("div");
      drawBox.className = "component-box";
      drawBox.style.left = `${startX * 100}%`;
      drawBox.style.top = `${startY * 100}%`;
      drawBox.style.width = "0%";
      drawBox.style.height = "0%";
      drawBox.style.border = "2px dashed var(--color-primary)";
      drawBox.style.backgroundColor = "rgba(37, 99, 235, 0.2)";
      this.overlayEl.appendChild(drawBox);

      const onPointerMove = (moveEvt) => {
        const curX = Math.max(0, Math.min(1, (moveEvt.clientX - rect.left) / rect.width));
        const curY = Math.max(0, Math.min(1, (moveEvt.clientY - rect.top) / rect.height));

        const x = Math.min(startX, curX);
        const y = Math.min(startY, curY);
        const w = Math.abs(curX - startX);
        const h = Math.abs(curY - startY);

        drawBox.style.left = `${x * 100}%`;
        drawBox.style.top = `${y * 100}%`;
        drawBox.style.width = `${w * 100}%`;
        drawBox.style.height = `${h * 100}%`;
      };

      const finish = (upEvt, cancelled = false) => {
        removeGesture();
        if (cancelled) {
          drawBox?.remove();
          drawBox = null;
          return;
        }

        const curX = Math.max(0, Math.min(1, (upEvt.clientX - rect.left) / rect.width));
        const curY = Math.max(0, Math.min(1, (upEvt.clientY - rect.top) / rect.height));

        const x = Math.round(Math.min(startX, curX) * 1000) / 1000;
        const y = Math.round(Math.min(startY, curY) * 1000) / 1000;
        const w = Math.round(Math.abs(curX - startX) * 1000) / 1000;
        const h = Math.round(Math.abs(curY - startY) * 1000) / 1000;

        if (drawBox) {
          drawBox.remove();
          drawBox = null;
        }

        // Min 1.5% in both dimensions
        if (w >= 0.015 && h >= 0.015 && this.onDrawnCallback) {
          this.onDrawnCallback({ x, y, w, h });
        } else {
          this.onDrawTooSmallCallback?.();
        }
      };
      const onPointerUp = (upEvt) => finish(upEvt);
      const onKeyDown = (keyEvt) => {
        if (keyEvt.key === "Escape") finish(null, true);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
      window.addEventListener("keydown", onKeyDown);
      removeGesture = () => {
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
        window.removeEventListener("keydown", onKeyDown);
        this._gestureCleanup = null;
      };
      this._gestureCleanup = removeGesture;
    };

    this.overlayEl.addEventListener("pointerdown", onPointerDown);
    this._cleanupDrawing = () => {
      this.overlayEl.removeEventListener("pointerdown", onPointerDown);
    };
  }

  disableDrawing() {
    this._gestureCleanup?.();
    if (this._cleanupDrawing) {
      this._cleanupDrawing();
      this._cleanupDrawing = null;
    }
    this.isDrawing = false;
    this.onDrawnCallback = null;
    this.onDrawTooSmallCallback = null;
    this.overlayEl?.classList.remove("image-stage__overlay--drawing");
  }

  destroy() {
    this.disableDrawing();
    this.container.innerHTML = "";
  }
}
