/**
 * Stepper navigation component.
 */

export const STEPS = [
  { key: "upload", number: 1, label: "Upload" },
  { key: "components", number: 2, label: "Components" },
  { key: "materials", number: 3, label: "Materials" },
  { key: "redesign", number: 4, label: "Redesign" },
  { key: "estimate", number: 5, label: "Estimate" },
  { key: "report", number: 6, label: "Report" },
];

export function renderStepper(container, currentStepKey, projectId, store) {
  if (!container || !projectId) return;

  const project = store.getState("project") || {};
  const photos = store.getState("photos") || [];
  const variants = store.getState("variants") || [];
  const activeVariantId = store.getState("activeVariantId");
  const activeVariant = variants.find((v) => v.id === activeVariantId);
  const selections = activeVariant?.selections || [];
  const generations = store.getState("generations") || [];
  const measurements = store.getState("measurements") || [];
  const reports = store.getState("reports") || [];

  // Determine completion per spec 03 §5
  const isUploadDone = photos.length > 0 || (project.photo_count || 0) > 0;
  const isComponentsDone = photos.some(
    (photo) => photo.quality_usable === true && photo.detected_at
  );
  const isMaterialsDone = selections.length > 0;
  const isRedesignDone = generations.some((g) => g.status === "succeeded");
  const isEstimateDone = measurements.some((m) =>
    selections.some((s) => s.component_id === m.component_id)
  );
  const isReportDone = reports.length > 0;

  const stepStatus = {
    upload: isUploadDone,
    components: isComponentsDone,
    materials: isMaterialsDone,
    redesign: isRedesignDone,
    estimate: isEstimateDone,
    report: isReportDone,
  };

  const html = STEPS.map((step) => {
    const isCurrent = step.key === currentStepKey;
    const isDone = stepStatus[step.key];

    let stateClass = "step-item--available";
    let icon = step.number;

    if (isCurrent) {
      stateClass = "step-item--current";
    } else if (isDone) {
      stateClass = "step-item--done";
      icon = "✓";
    }

    return `
      <li class="step-item ${stateClass}" data-step="${step.key}">
        <span class="step-bubble">${icon}</span>
        <span class="step-label">${step.label}</span>
      </li>
    `;
  }).join("");

  container.innerHTML = html;

  container.querySelectorAll(".step-item").forEach((el) => {
    el.addEventListener("click", () => {
      const targetStep = el.getAttribute("data-step");
      window.location.hash = `#/p/${projectId}/${targetStep}`;
    });
  });
}
