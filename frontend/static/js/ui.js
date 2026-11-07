/**
 * UI helpers: toasts, busy overlay, confirmation modal, and formatters.
 */

let busyInterval = null;
let busyStartTime = 0;

export function showToast(message, type = "info", duration = 6000, requestId = null) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.setAttribute("role", "alert");

  let reqHtml = "";
  if (requestId) {
    reqHtml = `<div class="toast-req-id">Ref: ${escapeHtml(requestId)}</div>`;
  }

  toast.innerHTML = `
    <div class="toast-body">
      <div>${escapeHtml(message)}</div>
      ${reqHtml}
    </div>
    <button class="toast-close" aria-label="Close">&times;</button>
  `;

  const closeBtn = toast.querySelector(".toast-close");
  closeBtn.addEventListener("click", () => toast.remove());

  container.appendChild(toast);

  if (type !== "error" && duration > 0) {
    setTimeout(() => {
      if (toast.isConnected) {
        toast.remove();
      }
    }, duration);
  }
}

export function showBusy(message = "Processing...") {
  const overlay = document.getElementById("busy-overlay");
  const msgEl = document.getElementById("busy-message");
  const timerEl = document.getElementById("busy-timer");
  const hintEl = document.getElementById("busy-hint");

  if (!overlay || !msgEl || !timerEl) return;

  msgEl.textContent = message;
  timerEl.textContent = "0s";
  if (hintEl) hintEl.classList.add("hidden");

  overlay.classList.remove("hidden");
  busyStartTime = Date.now();

  clearInterval(busyInterval);
  busyInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - busyStartTime) / 1000);
    timerEl.textContent = `${elapsed}s`;
    if (elapsed >= 20 && hintEl) {
      hintEl.classList.remove("hidden");
    }
  }, 1000);
}

export function hideBusy() {
  const overlay = document.getElementById("busy-overlay");
  if (overlay) {
    overlay.classList.add("hidden");
  }
  clearInterval(busyInterval);
}

export function confirmModal(title, message) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirm-modal");
    const titleEl = document.getElementById("modal-title");
    const msgEl = document.getElementById("modal-message");
    const cancelBtn = document.getElementById("modal-btn-cancel");
    const confirmBtn = document.getElementById("modal-btn-confirm");

    if (!modal) {
      resolve(window.confirm(`${title}\n\n${message}`));
      return;
    }

    titleEl.textContent = title;
    msgEl.textContent = message;
    modal.classList.remove("hidden");

    function cleanup(result) {
      modal.classList.add("hidden");
      cancelBtn.removeEventListener("click", onCancel);
      confirmBtn.removeEventListener("click", onConfirm);
      window.removeEventListener("keydown", onKey);
      resolve(result);
    }

    function onCancel() { cleanup(false); }
    function onConfirm() { cleanup(true); }
    function onKey(e) {
      if (e.key === "Escape") cleanup(false);
    }

    cancelBtn.addEventListener("click", onCancel);
    confirmBtn.addEventListener("click", onConfirm);
    window.addEventListener("keydown", onKey);
  });
}

// Formatters
export function formatCurrency(value, currency = "INR") {
  if (value === null || value === undefined || isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency,
    maximumFractionDigits: value > 1000 ? 0 : 2,
  }).format(value);
}

export function formatArea(sqft) {
  if (sqft === null || sqft === undefined) return "—";
  return `${new Intl.NumberFormat("en-IN").format(Math.round(sqft))} sq ft`;
}

export function formatLength(ft) {
  if (ft === null || ft === undefined) return "—";
  return `${new Intl.NumberFormat("en-IN").format(Math.round(ft))} ft`;
}

export function formatPercent(pct) {
  if (pct === null || pct === undefined) return "—";
  return `${pct}%`;
}

export function formatDate(isoString) {
  if (!isoString) return "—";
  try {
    const date = new Date(isoString);
    return date.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

export function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

export function clearElement(el) {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

