/** Resolve the Components screen state from the persisted photo and working set. */
export function getDetectionViewState(photo, components = [], error = null, manual = false) {
  if (manual) return "manual";
  if (!photo) return "no-photo";
  if (error) return "failed";
  if (photo.quality_usable === false && photo.detected_at) return "unusable";
  if (components.length > 0) return "ready";
  if (photo.quality_usable === true && photo.detected_at && components.length === 0) {
    return "empty";
  }
  if (photo.quality_usable === true && photo.detected_at && components.length > 0) {
    return "ready";
  }
  return "not-detected";
}
