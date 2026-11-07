"""Gemini Vision detection orchestration and persistence."""

import logging
import math
import re
import sqlite3
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import Settings
from app.core.database import transaction
from app.core.errors import AIError, AppError, ConflictError, NotFoundError
from app.core.storage import StorageManager
from app.core.timeutil import utc_now
from app.repositories import component_repo, photo_repo, project_repo, stage_run_repo
from app.schemas.common import COMPONENT_TYPES
from app.schemas.detection import DetectionEnvelope
from app.services.ai import get_vision_client
from app.services.ai.image_prep import prepare_working_image
from app.services.catalogue_compatibility import supported_component_types

logger = logging.getLogger(__name__)

PROMPT_VERSION = "det-v2"
MAX_DETECTED_COMPONENTS = 40
MAX_OTHER_COMPONENTS = 5
MIN_BOX_SIZE = 0.02
DEFAULT_UNUSABLE_REASON = (
    "This image can't be used. Please upload a clear exterior photograph or "
    "3D architectural rendering of the whole house."
)
_DISPLAY_LABELS = {
    component_type: component_type.replace("_", " ").capitalize()
    for component_type in COMPONENT_TYPES
}
_PROMPT = """You are analysing an exterior image of a residential building to help
plan a renovation. Accept real residential exterior photographs, 3D architectural renderings,
CGI exterior visualizations, and other computer-generated images of residential buildings.
Identify visible exterior components in both photographs and rendered images. Do not mark an image unusable merely because it is digitally rendered or computer-generated.

TASK
1. Decide whether the image is usable for exterior renovation planning.
2. List the visible exterior components of the main building with approximate
   bounding boxes.

OUTPUT
Reply with ONLY one JSON object, no other text, in exactly this shape:
{"usable": boolean, "quality_reason": string or null,
 "components": [{"type": string, "label": string,
                 "box_2d": [ymin, xmin, ymax, xmax], "confidence": number}]}

RULES FOR box_2d
- Four integers on a 0-1000 scale, relative to the full image.
- Order is [ymin, xmin, ymax, xmax]. Origin is the top-left corner.
- The box must tightly enclose the component.

COMPONENT TYPES
- wall: one entry per visible wall section of the main building; the box may
  contain windows and doors.
- window, door, railing, pillar, parapet, gate: one entry per individual item.
- balcony: the balcony structure itself, not its railing.
- roof_edge: roof edge, eave or fascia trim.
- other: notable non-building items (pavement, vehicles, trees, signs), at most 5.
  Do not report sky or distant background.
Use only: wall, window, door, balcony, railing, pillar, parapet, gate,
roof_edge, other.

LABELS
- 3 to 10 words describing which one it is, including floor and side where
  possible. Labels should be unique within the reply.

LIMITS
- Report at most 40 components. Prefer larger and more important components.
- Do not invent components that are not visible.
- confidence is a number from 0 to 1.

USABILITY
- Set usable to false if it is too blurry to identify surfaces, extremely dark
  or overexposed, does not show a recognizable residential exterior, is an
  interior, shows a building that is mostly hidden or cropped, or is a floor plan
  or unrelated drawing that cannot support exterior component identification.
- A clear exterior rendering or computer-generated image is usable just like a
  photograph. Do not reject it because it is not a real photograph.
- If usable is false, set quality_reason to one or two short sentences telling
  the owner what kind of clearer exterior image to upload, and return an empty
  components list.
- If usable is true, quality_reason may contain one short advisory sentence
  or null."""


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _normalize_component(
    entry: Any,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not isinstance(entry, dict):
        return None, "invalid"
    component_type = entry.get("type")
    box = entry.get("box_2d")
    if (
        not isinstance(component_type, str)
        or not isinstance(box, list)
        or len(box) != 4
        or not all(_finite_number(value) for value in box)
    ):
        return None, "invalid"

    normalized_type = re.sub(r"[\s-]+", "_", component_type.strip().lower())
    remapped = normalized_type not in COMPONENT_TYPES
    if remapped:
        normalized_type = "other"

    ymin, xmin, ymax, xmax = [max(0.0, min(1000.0, float(v))) for v in box]
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    x, y = xmin / 1000, ymin / 1000
    w, h = (xmax - xmin) / 1000, (ymax - ymin) / 1000
    if w < MIN_BOX_SIZE or h < MIN_BOX_SIZE:
        return None, "small"

    label = entry.get("label")
    if isinstance(label, str):
        label = " ".join(
            "".join(
                char
                for char in label
                if unicodedata.category(char) not in {"Cc", "Cf"}
            ).split()
        )[:120]
    if not label:
        label = _DISPLAY_LABELS[normalized_type]

    confidence = entry.get("confidence")
    confidence_value = (
        max(0.0, min(1.0, float(confidence)))
        if _finite_number(confidence)
        else None
    )
    return {
        "type": normalized_type,
        "label": label,
        "box_x": round(x, 4),
        "box_y": round(y, 4),
        "box_w": round(w, 4),
        "box_h": round(h, 4),
        "confidence": confidence_value,
        "area": w * h,
    }, "remapped" if remapped else "valid"


def _iou(first: Dict[str, Any], second: Dict[str, Any]) -> float:
    left = max(first["box_x"], second["box_x"])
    top = max(first["box_y"], second["box_y"])
    right = min(first["box_x"] + first["box_w"], second["box_x"] + second["box_w"])
    bottom = min(first["box_y"] + first["box_h"], second["box_y"] + second["box_h"])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0
    union = first["area"] + second["area"] - intersection
    return intersection / union if union else 0.0


def _normalize_set(entries: List[Any]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    counts = {
        "raw_count": len(entries),
        "dropped_invalid": 0,
        "dropped_small": 0,
        "dropped_duplicate": 0,
        "remapped_types": 0,
        "dropped_over_limit": 0,
    }
    valid: List[Dict[str, Any]] = []
    for entry in entries:
        component, result = _normalize_component(entry)
        if component is None:
            counts["dropped_small" if result == "small" else "dropped_invalid"] += 1
            continue
        if result == "remapped":
            counts["remapped_types"] += 1
        valid.append(component)

    deduplicated: List[Dict[str, Any]] = []
    for component in valid:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(deduplicated)
                if existing["type"] == component["type"]
                and _iou(existing, component) >= 0.85
            ),
            None,
        )
        if duplicate_index is None:
            deduplicated.append(component)
            continue
        counts["dropped_duplicate"] += 1
        existing = deduplicated[duplicate_index]
        if (component["confidence"] if component["confidence"] is not None else -1) > (
            existing["confidence"] if existing["confidence"] is not None else -1
        ):
            deduplicated[duplicate_index] = component

    others = [component for component in deduplicated if component["type"] == "other"]
    if len(others) > MAX_OTHER_COMPONENTS:
        largest_others = sorted(others, key=lambda item: item["area"], reverse=True)[
            :MAX_OTHER_COMPONENTS
        ]
        kept_other_ids = {id(item) for item in largest_others}
        counts["dropped_over_limit"] += len(others) - len(largest_others)
        deduplicated = [
            item
            for item in deduplicated
            if item["type"] != "other" or id(item) in kept_other_ids
        ]

    if len(deduplicated) > MAX_DETECTED_COMPONENTS:
        walls = [item for item in deduplicated if item["type"] == "wall"]
        others = [item for item in deduplicated if item["type"] != "wall"]
        confidence_key = lambda item: (
            item["confidence"] if item["confidence"] is not None else -1
        )
        if len(walls) >= MAX_DETECTED_COMPONENTS:
            selected = sorted(walls, key=confidence_key, reverse=True)[
                :MAX_DETECTED_COMPONENTS
            ]
        else:
            selected = walls + sorted(
                others,
                key=confidence_key,
                reverse=True,
            )[: MAX_DETECTED_COMPONENTS - len(walls)]
        counts["dropped_over_limit"] += len(deduplicated) - len(selected)
        deduplicated = selected

    seen_labels: set[str] = set()
    for component in deduplicated:
        base_label = component["label"]
        candidate = base_label
        suffix = 2
        while candidate in seen_labels:
            ending = f" {suffix}"
            candidate = f"{base_label[:120 - len(ending)]}{ending}"
            suffix += 1
        component["label"] = candidate
        seen_labels.add(candidate)
    return deduplicated, counts


def _component_response(
    row: Dict[str, Any], supported_types: set[str]
) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "photo_id": row["photo_id"],
        "type": row["type"],
        "label": row["label"],
        "box": {
            "x": row["box_x"],
            "y": row["box_y"],
            "w": row["box_w"],
            "h": row["box_h"],
        },
        "confidence": row["confidence"],
        "origin": row["origin"],
        "is_locked": bool(row["is_locked"]),
        "supported": row["type"] in supported_types,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _existing_components(
    conn: sqlite3.Connection,
    project_id: str,
    photo_id: str,
    supported_types: set[str],
) -> List[Dict[str, Any]]:
    return [
        _component_response(row, supported_types)
        for row in component_repo.list_by_project(conn, project_id, photo_id)
    ]


def _warning_messages(
    counts: Dict[str, int],
    removed_selections: int = 0,
    removed_measurements: int = 0,
    skipped_overlap: int = 0,
    zero_components: bool = False,
    max_components: int = MAX_DETECTED_COMPONENTS,
) -> List[str]:
    warnings: List[str] = []
    if skipped_overlap:
        warnings.append(
            f"{skipped_overlap} detected regions were hidden because they overlap regions you edited."
        )
    if counts["dropped_small"]:
        warnings.append(f"{counts['dropped_small']} very small regions were ignored.")
    if counts["dropped_duplicate"]:
        warnings.append(f"{counts['dropped_duplicate']} duplicate regions were merged.")
    if counts["dropped_invalid"]:
        warnings.append(f"{counts['dropped_invalid']} invalid region entries were ignored.")
    if counts["remapped_types"]:
        warnings.append(
            f"{counts['remapped_types']} regions with unrecognised types were marked as Other."
        )
    if removed_selections or removed_measurements:
        warnings.append(
            "Replacing the previous results removed "
            f"{removed_selections} material choice(s) and {removed_measurements} "
            "measurement(s) linked to those regions."
        )
    if counts["dropped_over_limit"]:
        warnings.append(
            f"Only the first {max_components} regions were kept."
        )
    if zero_components:
        warnings.append("No components were found. You can add regions manually.")
    return warnings


def _safe_error(exc: Exception) -> Tuple[str, str]:
    if isinstance(exc, AppError):
        return exc.code, exc.message
    return "INTERNAL_ERROR", "Something went wrong on our side. Please try again."


def detect_components(
    conn: sqlite3.Connection,
    storage: StorageManager,
    settings: Settings,
    catalogue: Dict[str, Any],
    project_id: str,
    photo_id: str,
) -> Dict[str, Any]:
    """Run detection and atomically replace only unlocked AI components."""
    project = project_repo.get_by_id(conn, project_id)
    if project is None:
        raise NotFoundError("project")
    photo = photo_repo.get_by_id(conn, photo_id, project_id)
    if photo is None:
        raise NotFoundError("photo")

    with transaction(conn, immediate=True):
        running = conn.execute(
            "SELECT 1 FROM stage_runs WHERE project_id = ? AND stage = 'detection' AND status = 'running' LIMIT 1;",
            (project_id,),
        ).fetchone()
        if running:
            raise ConflictError(
                details={"reason": "detection_in_progress"},
                message="A detection is already running for this project.",
            )
        run = stage_run_repo.create(conn, project_id, "detection")

    started = time.monotonic()
    run_id = run["id"]
    support = supported_component_types(catalogue)
    stage_detail: Dict[str, Any] = {
        "model": settings.GEMINI_VISION_MODEL or "mock-vision",
        "prompt_version": PROMPT_VERSION,
        "attempts": 0,
        "image_sent": {},
    }
    try:
        try:
            original_bytes = storage.read_bytes(photo["stored_path"])
            working_image = prepare_working_image(original_bytes, settings)
        except Exception as exc:
            logger.exception(
                "Could not preprocess stored photo for detection",
                extra={"project_id": project_id, "photo_id": photo_id, "stage_run_id": run_id},
            )
            raise AppError(
                "INTERNAL_ERROR",
                "The stored photo could not be prepared for analysis.",
                500,
            ) from exc

        stage_detail["image_sent"] = {
            "width_px": working_image.width_px,
            "height_px": working_image.height_px,
            "bytes": len(working_image.bytes),
        }
        vision_result = get_vision_client(settings).analyze_image(
            working_image,
            _PROMPT,
            DetectionEnvelope,
            PROMPT_VERSION,
        )
        stage_detail.update(
            {
                "model": vision_result.model_name,
                "attempts": vision_result.attempts,
                "response_excerpt": vision_result.raw_text_excerpt[:500],
            }
        )
        envelope = vision_result.data
        quality_reason = (envelope.quality_reason or "").strip()[:200] or None

        if not envelope.usable:
            quality_reason = quality_reason or DEFAULT_UNUSABLE_REASON
            with transaction(conn, immediate=True):
                updated_photo = photo_repo.update_quality(
                    conn,
                    photo_id,
                    False,
                    quality_reason,
                    project_id=project_id,
                )
                stage_detail.update({"usable": False, "raw_count": len(envelope.components)})
                stage_run_repo.update_completed(
                    conn,
                    run_id,
                    "succeeded",
                    detail=stage_detail,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            return {
                "stage_run_id": run_id,
                "photo": _photo_response(updated_photo),
                "usable": False,
                "quality_reason": quality_reason,
                "components": _existing_components(
                    conn, project_id, photo_id, support
                ),
                "kept_locked_count": component_repo.count_locked_by_photo(
                    conn, project_id, photo_id
                ),
                "warnings": [],
            }

        normalized, counts = _normalize_set(envelope.components)
        stage_detail.update(counts)
        skipped_overlap = 0
        removed_selections = 0
        removed_measurements = 0
        inserted = 0
        with transaction(conn, immediate=True):
            detected_rows = [
                component_repo.create_detected(
                    conn,
                    project_id,
                    photo_id,
                    run_id,
                    item["type"],
                    item["label"],
                    item["box_x"],
                    item["box_y"],
                    item["box_w"],
                    item["box_h"],
                    item["confidence"],
                )
                for item in normalized
            ]
            removed_selections, removed_measurements = (
                component_repo.count_attached_data_for_unlocked_ai(
                    conn, project_id, photo_id
                )
            )
            component_repo.delete_unlocked_ai_by_photo(conn, project_id, photo_id)
            locked_components = [
                row
                for row in component_repo.list_by_project(conn, project_id, photo_id)
                if row["is_locked"]
            ]
            kept_locked_count = len(locked_components)

            for item, detected in zip(normalized, detected_rows):
                overlaps = any(
                    row["type"] == item["type"]
                    and _iou(
                        item,
                        {
                            "box_x": row["box_x"],
                            "box_y": row["box_y"],
                            "box_w": row["box_w"],
                            "box_h": row["box_h"],
                            "area": row["box_w"] * row["box_h"],
                        },
                    )
                    >= 0.5
                    for row in locked_components
                )
                if overlaps:
                    skipped_overlap += 1
                    continue
                if len(locked_components) + inserted >= settings.MAX_COMPONENTS_PER_PHOTO:
                    counts["dropped_over_limit"] += 1
                    continue

                component_repo.create(
                    conn,
                    project_id,
                    photo_id,
                    item["type"],
                    item["label"],
                    item["box_x"],
                    item["box_y"],
                    item["box_w"],
                    item["box_h"],
                    confidence=item["confidence"],
                    origin="ai",
                    source_detection_id=detected["id"],
                    is_locked=0,
                )
                inserted += 1

            updated_photo = photo_repo.update_quality(
                conn,
                photo_id,
                True,
                quality_reason,
                project_id=project_id,
            )
            project_repo.touch_updated_at(conn, project_id)
            stage_detail.update(
                {
                    "usable": True,
                    "inserted": inserted,
                    "kept_locked": kept_locked_count,
                    "removed_selections": removed_selections,
                    "removed_measurements": removed_measurements,
                    "skipped_overlap": skipped_overlap,
                    "dropped_over_limit": counts["dropped_over_limit"],
                }
            )
            stage_run_repo.update_completed(
                conn,
                run_id,
                "succeeded",
                detail=stage_detail,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        current_components = _existing_components(conn, project_id, photo_id, support)
        warnings = _warning_messages(
            counts,
            removed_selections=removed_selections,
            removed_measurements=removed_measurements,
            skipped_overlap=skipped_overlap,
            zero_components=not normalized,
            max_components=settings.MAX_COMPONENTS_PER_PHOTO,
        )
        return {
            "stage_run_id": run_id,
            "photo": _photo_response(updated_photo),
            "usable": True,
            "quality_reason": quality_reason,
            "components": current_components,
            "kept_locked_count": kept_locked_count,
            "warnings": warnings,
        }
    except Exception as exc:
        error_code, error_message = _safe_error(exc)
        try:
            with transaction(conn, immediate=True):
                stage_run_repo.update_completed(
                    conn,
                    run_id,
                    "failed",
                    error_code=error_code,
                    error_message=error_message,
                    detail=stage_detail,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        except Exception:
            logger.exception(
                "Could not mark detection stage run failed",
                extra={"project_id": project_id, "stage_run_id": run_id},
            )
        if isinstance(exc, (AppError, AIError)):
            raise
        logger.exception(
            "Detection failed unexpectedly",
            extra={"project_id": project_id, "stage_run_id": run_id},
        )
        raise AppError(
            "INTERNAL_ERROR",
            "Something went wrong on our side. Please try again.",
            500,
        ) from exc


def _photo_response(photo: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(photo)
    result["quality_usable"] = (
        None if photo["quality_usable"] is None else bool(photo["quality_usable"])
    )
    result["image_url"] = (
        f"/api/projects/{photo['project_id']}/photos/{photo['id']}/image"
    )
    return result
