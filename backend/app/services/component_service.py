"""Component CRUD, locking, catalogue compatibility and cascade effects."""

import math
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import Settings
from app.core.database import transaction
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.repositories import (
    component_repo,
    measurement_repo,
    photo_repo,
    project_repo,
    selection_repo,
)
from app.schemas.common import COMPONENT_TYPES
from app.services.catalogue_compatibility import (
    compatible_material_ids,
    supported_component_types,
)


def _clean_label(value: str) -> str:
    return "".join(
        character
        for character in value
        if unicodedata.category(character) not in {"Cc", "Cf"}
    ).strip()[:120]


def _normalize_box(box: Any) -> Dict[str, float]:
    if isinstance(box, dict):
        x, y, width, height = (
            float(box[key]) for key in ("x", "y", "w", "h")
        )
    else:
        x, y, width, height = (
            float(box.x),
            float(box.y),
            float(box.w),
            float(box.h),
        )
    if not all(math.isfinite(value) for value in (x, y, width, height)):
        raise ValidationAppError(
            "The region box must contain finite values.",
            {"fields": [{"field": "box", "problem": "must contain finite numbers"}]},
        )
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x > 1 or y > 1:
        raise ValidationAppError(
            "The region box must fit within the photo.",
            {"fields": [{"field": "box", "problem": "must fit within the photo"}]},
        )
    right, bottom = x + width, y + height
    if right > 1.001 or bottom > 1.001:
        raise ValidationAppError(
            "The region box must fit within the photo.",
            {"fields": [{"field": "box", "problem": "must fit within the photo"}]},
        )
    width = min(width, 1.0 - x)
    height = min(height, 1.0 - y)
    values = {
        "box_x": round(x, 4),
        "box_y": round(y, 4),
        "box_w": round(width, 4),
        "box_h": round(height, 4),
    }
    if values["box_w"] < 0.02 or values["box_h"] < 0.02:
        raise ValidationAppError(
            "A region must be at least 2% of the photo in both directions.",
            {
                "fields": [
                    {"field": "box", "problem": "width and height must each be at least 0.02"}
                ]
            },
        )
    return values


def _response(row: Dict[str, Any], catalogue: Dict[str, Any]) -> Dict[str, Any]:
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
        "supported": row["type"] in supported_component_types(catalogue),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_components(
    conn: sqlite3.Connection,
    project_id: str,
    catalogue: Dict[str, Any],
    photo_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    if photo_id is not None and photo_repo.get_by_id(conn, photo_id, project_id) is None:
        raise NotFoundError("photo")
    rows = component_repo.list_by_project(conn, project_id, photo_id)
    return {"items": [_response(row, catalogue) for row in rows]}


def create_component(
    conn: sqlite3.Connection,
    settings: Settings,
    project_id: str,
    catalogue: Dict[str, Any],
    photo_id: str,
    component_type: str,
    label: Optional[str],
    box: Any,
) -> Dict[str, Any]:
    if component_type not in COMPONENT_TYPES:
        raise ValidationAppError(
            "Unknown component type.",
            {"fields": [{"field": "type", "problem": "must be a supported component type"}]},
        )
    normalized_box = _normalize_box(box)
    clean_label = _clean_label(label or "") or component_type.replace("_", " ").capitalize()
    with transaction(conn, immediate=True):
        if photo_repo.get_by_id(conn, photo_id, project_id) is None:
            raise NotFoundError("photo")
        if component_repo.count_by_photo(conn, project_id, photo_id) >= settings.MAX_COMPONENTS_PER_PHOTO:
            raise ConflictError(
                details={"reason": "component_limit"},
                message="This photo already has the maximum number of regions.",
            )
        row = component_repo.create(
            conn,
            project_id,
            photo_id,
            component_type,
            clean_label,
            normalized_box["box_x"],
            normalized_box["box_y"],
            normalized_box["box_w"],
            normalized_box["box_h"],
            origin="user",
            is_locked=1,
        )
        project_repo.touch_updated_at(conn, project_id)
    return _response(row, catalogue)


def update_component(
    conn: sqlite3.Connection,
    project_id: str,
    component_id: str,
    catalogue: Dict[str, Any],
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    with transaction(conn, immediate=True):
        existing = component_repo.get_by_id(conn, component_id, project_id)
        if existing is None:
            raise NotFoundError("component")

        updates: Dict[str, Any] = {}
        if "type" in changes and changes["type"] != existing["type"]:
            updates["type"] = changes["type"]
        if "label" in changes:
            label = _clean_label(changes["label"])
            if not label:
                raise ValidationAppError(
                    "Label must contain 1-120 characters.",
                    {"fields": [{"field": "label", "problem": "must contain 1-120 characters"}]},
                )
            if label != existing["label"]:
                updates["label"] = label
        if "box" in changes:
            normalized_box = _normalize_box(changes["box"])
            if any(
                normalized_box[key] != round(float(existing[column]), 4)
                for key, column in (
                    ("box_x", "box_x"),
                    ("box_y", "box_y"),
                    ("box_w", "box_w"),
                    ("box_h", "box_h"),
                )
            ):
                updates.update(normalized_box)

        if not updates:
            return {
                "component": _response(existing, catalogue),
                "removed_selections": 0,
                "removed_ai_measurement": False,
                "warnings": [],
            }

        removed_selections = 0
        removed_ai_measurement = False
        measurement = measurement_repo.get_by_component(conn, component_id)
        geometric_change = "type" in updates or any(
            field.startswith("box_") for field in updates
        )
        if "type" in updates:
            compatible_ids = compatible_material_ids(updates["type"], catalogue)
            removed_selections = selection_repo.delete_incompatible_for_component(
                conn, component_id, compatible_ids
            )
        if geometric_change and measurement:
            if measurement["source"] == "ai_estimate":
                removed_ai_measurement = measurement_repo.delete_ai_estimates_for_component(
                    conn, component_id
                )

        row = component_repo.update(conn, component_id, project_id, **updates)
        project_repo.touch_updated_at(conn, project_id)

        warnings: List[str] = []
        if removed_selections:
            warnings.append(
                f"{removed_selections} material choice(s) were removed because the new type does not support them."
            )
        if removed_ai_measurement:
            warnings.append(
                "The AI-estimated measurement for this region was removed because the region changed."
            )
        if geometric_change and measurement and measurement["source"] == "user":
            warnings.append(
                "Your measurement for this region was kept. Please check it still applies."
            )
    return {
        "component": _response(row, catalogue),
        "removed_selections": removed_selections,
        "removed_ai_measurement": removed_ai_measurement,
        "warnings": warnings,
    }


def delete_component(
    conn: sqlite3.Connection, project_id: str, component_id: str
) -> None:
    with transaction(conn, immediate=True):
        component_repo.delete(conn, component_id, project_id)
        project_repo.touch_updated_at(conn, project_id)
