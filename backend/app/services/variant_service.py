"""Design variant and material selection business operations."""

import json
import logging
import re
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import Settings
from app.core.database import transaction
from app.core.errors import CatalogueError, ConflictError, NotFoundError, ValidationAppError
from app.core.storage import StorageManager
from app.repositories import (
    component_repo,
    generation_repo,
    project_repo,
    selection_repo,
    variant_repo,
)
from app.services import catalogue_service

logger = logging.getLogger(__name__)
MAX_VARIANTS_PER_PROJECT = 10
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def list_variants(
    conn: sqlite3.Connection, project_id: str, active_variant_id: Optional[str]
) -> Dict[str, List[Dict[str, Any]]]:
    variants = variant_repo.list_by_project(conn, project_id)
    return {
        "items": [
            {
                **variant,
                "is_active": variant["id"] == active_variant_id,
                "selections": selection_repo.list_by_variant(conn, variant["id"]),
            }
            for variant in variants
        ]
    }


def create_variant(
    conn: sqlite3.Connection,
    project_id: str,
    name: Optional[str],
    copy_from_variant_id: Optional[str],
) -> Dict[str, Any]:
    with transaction(conn, immediate=True):
        if copy_from_variant_id is not None and not variant_repo.get_by_id(
            conn, copy_from_variant_id, project_id
        ):
            raise NotFoundError("variant")
        if variant_repo.count_by_project(conn, project_id) >= MAX_VARIANTS_PER_PROJECT:
            raise ConflictError(
                details={"reason": "variant_limit"},
                message=f"A project can have at most {MAX_VARIANTS_PER_PROJECT} designs.",
            )
        final_name = _clean_variant_name(name) if name is not None else _next_name(conn, project_id)
        _ensure_unique_name(conn, project_id, final_name)
        variant = variant_repo.create(conn, project_id, final_name)
        if copy_from_variant_id is not None:
            selection_repo.copy_variant_selections(
                conn, copy_from_variant_id, variant["id"]
            )
            variant_repo.touch_updated_at(conn, variant["id"])
            variant = variant_repo.get_by_id(conn, variant["id"], project_id) or variant
        project_repo.touch_updated_at(conn, project_id)
        return {
            **variant,
            "is_active": False,
            "selections": selection_repo.list_by_variant(conn, variant["id"]),
        }


def rename_variant(
    conn: sqlite3.Connection, project_id: str, variant_id: str, name: str
) -> Dict[str, Any]:
    with transaction(conn, immediate=True):
        variant = variant_repo.get_by_id(conn, variant_id, project_id)
        if variant is None:
            raise NotFoundError("variant")
        final_name = _clean_variant_name(name)
        _ensure_unique_name(conn, project_id, final_name, variant_id)
        updated = variant_repo.update(conn, variant_id, project_id, final_name)
        project_repo.touch_updated_at(conn, project_id)
        return {
            **updated,
            "is_active": _is_active(conn, project_id, variant_id),
            "selections": selection_repo.list_by_variant(conn, variant_id),
        }


def delete_variant(
    conn: sqlite3.Connection,
    storage: StorageManager,
    project_id: str,
    variant_id: str,
) -> None:
    with transaction(conn, immediate=True):
        variant = variant_repo.get_by_id(conn, variant_id, project_id)
        if variant is None:
            raise NotFoundError("variant")
        paths = generation_repo.list_image_paths_by_variant(conn, project_id, variant_id)
        variant_repo.delete(conn, variant_id, project_id)
        project_repo.touch_updated_at(conn, project_id)
    for path in paths:
        try:
            storage.delete_file(path)
        except OSError:
            logger.warning(
                "Could not remove deleted variant generation file",
                extra={"project_id": project_id, "variant_id": variant_id},
                exc_info=True,
            )


def set_selection(
    conn: sqlite3.Connection,
    project_id: str,
    variant_id: str,
    component_id: str,
    payload: Dict[str, Any],
    catalogue: Dict[str, Any],
) -> Dict[str, Any]:
    material_id = payload["material_id"]
    with transaction(conn, immediate=True):
        variant = variant_repo.get_by_id(conn, variant_id, project_id)
        component = component_repo.get_by_id(conn, component_id, project_id)
        if variant is None or component is None:
            raise NotFoundError("variant" if variant is None else "component")

        material = catalogue_service.get_material(catalogue, material_id)
        if material is None:
            raise CatalogueError("This material is not available.")
        if not catalogue_service.is_compatible(
            catalogue, material_id, component["type"]
        ):
            type_label = component["type"].replace("_", " ")
            raise CatalogueError(
                f"{material['name']} cannot be used on a {type_label}."
            )
        params = _clean_selection_params(payload.get("params", {}), material)
        selection = selection_repo.upsert(
            conn, variant_id, component_id, material_id, params
        )
        variant_repo.touch_updated_at(conn, variant_id)
        project_repo.touch_updated_at(conn, project_id)
        return selection


def remove_selection(
    conn: sqlite3.Connection,
    project_id: str,
    variant_id: str,
    component_id: str,
) -> None:
    with transaction(conn, immediate=True):
        if variant_repo.get_by_id(conn, variant_id, project_id) is None:
            raise NotFoundError("variant")
        selection_repo.delete(conn, variant_id, component_id)
        variant_repo.touch_updated_at(conn, variant_id)
        project_repo.touch_updated_at(conn, project_id)


def _clean_variant_name(name: str) -> str:
    cleaned = "".join(
        char for char in name if unicodedata.category(char) not in {"Cc", "Cf"}
    ).strip()
    if not 1 <= len(cleaned) <= 60:
        raise ValidationAppError(
            "Design name must contain 1-60 characters.",
            {"fields": [{"field": "name", "problem": "must contain 1-60 characters"}]},
        )
    return cleaned


def _ensure_unique_name(
    conn: sqlite3.Connection,
    project_id: str,
    name: str,
    exclude_variant_id: Optional[str] = None,
) -> None:
    if variant_repo.find_name(conn, project_id, name, exclude_variant_id):
        raise ConflictError(
            details={"reason": "duplicate_name"},
            message=f"A design named '{name}' already exists in this project.",
        )


def _next_name(conn: sqlite3.Connection, project_id: str) -> str:
    existing = {
        variant["name"].casefold()
        for variant in variant_repo.list_by_project(conn, project_id)
    }
    index = 1
    while f"design {index}".casefold() in existing:
        index += 1
    return f"Design {index}"


def _is_active(conn: sqlite3.Connection, project_id: str, variant_id: str) -> bool:
    row = conn.execute(
        "SELECT active_variant_id FROM projects WHERE id = ?;", (project_id,)
    ).fetchone()
    return bool(row and row["active_variant_id"] == variant_id)


def _clean_selection_params(
    params: Any, material: Dict[str, Any]
) -> Dict[str, str]:
    if not isinstance(params, dict):
        raise ValidationAppError(
            "Selection parameters must be an object.",
            {"fields": [{"field": "params", "problem": "must be an object"}]},
        )
    extra = set(params) - {"color_hex", "note"}
    if extra:
        raise ValidationAppError(
            "Selection parameters contain unsupported fields.",
            {"fields": [{"field": f"params.{key}", "problem": "is not allowed"} for key in sorted(extra)]},
        )
    result: Dict[str, str] = {}
    if "color_hex" in params:
        color = params["color_hex"]
        if not isinstance(color, str) or not _COLOR.fullmatch(color) or not catalogue_service.allows_color(material):
            raise ValidationAppError(
                "Colour can only be set for paint and texture finishes using #RRGGBB.",
                {"fields": [{"field": "params.color_hex", "problem": "must be #RRGGBB and is only allowed for paint or texture finishes"}]},
            )
        result["color_hex"] = color.upper()
    if "note" in params:
        note = params["note"]
        if not isinstance(note, str):
            raise ValidationAppError(
                "Selection note must be text.",
                {"fields": [{"field": "params.note", "problem": "must be a string"}]},
            )
        note = "".join(
            char for char in note
            if unicodedata.category(char) not in {"Cc", "Cf"}
        ).strip()
        if len(note) > 100:
            raise ValidationAppError(
                "Selection note must be at most 100 characters.",
                {"fields": [{"field": "params.note", "problem": "must be at most 100 characters"}]},
            )
        if note:
            result["note"] = note
    return result
