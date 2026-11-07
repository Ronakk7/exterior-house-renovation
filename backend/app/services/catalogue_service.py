"""Validated, read-only material catalogue operations."""

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.common import COMPONENT_TYPES
from app.services.catalogue_compatibility import (
    compatible_material_ids,
    is_material_compatible,
)

_MATERIAL_ID = re.compile(r"^[a-z0-9_]{3,60}$")
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PRICING_UNITS = {"sqft", "rft"}
_REQUIRED_SUPPORTED_TYPES = {"wall", "pillar", "railing"}


def load_catalogue(catalogue_path: str) -> Dict[str, Any]:
    """Load, validate, and derive compatibility data from the catalogue file."""
    path = Path(catalogue_path)
    if not path.is_file():
        fallback = Path(__file__).resolve().parents[1] / "data" / "catalogue.json"
        if fallback.is_file():
            path = fallback
        else:
            raise RuntimeError(f"Catalogue file not found at {catalogue_path} or {fallback}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load catalogue file {path}: {exc}") from exc
    validate_catalogue(data, str(path))
    data["type_map"] = {
        component_type: compatible_material_ids(component_type, data)
        for component_type in COMPONENT_TYPES
        if compatible_material_ids(component_type, data)
    }
    return data


def validate_catalogue(data: Any, source: str = "catalogue") -> None:
    """Validate all catalogue invariants before the app starts."""
    def fail(problem: str) -> None:
        raise RuntimeError(f"Invalid catalogue {source}: {problem}")

    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        fail("version must be a string")
    categories = data.get("categories")
    materials = data.get("materials")
    if not isinstance(categories, list) or not isinstance(materials, list):
        fail("categories and materials must be arrays")

    category_ids: set[str] = set()
    for category in categories:
        if not isinstance(category, dict) or not _nonempty_string(category.get("id")) or not _nonempty_string(category.get("name")):
            fail("each category must have a non-empty id and name")
        if category["id"] in category_ids:
            fail(f"duplicate category ID {category['id']}")
        category_ids.add(category["id"])

    material_ids: set[str] = set()
    type_units: Dict[str, str] = {}
    supported: set[str] = set()
    for material in materials:
        if not isinstance(material, dict):
            fail("each material must be an object")
        material_id = material.get("id")
        if not isinstance(material_id, str) or not _MATERIAL_ID.fullmatch(material_id):
            fail(f"invalid material ID {material_id!r}")
        if material_id in material_ids:
            fail(f"duplicate material ID {material_id}")
        material_ids.add(material_id)
        if not isinstance(material.get("name"), str) or not 3 <= len(material["name"]) <= 60:
            fail(f"{material_id}: name must be 3-60 characters")
        if material.get("category") not in category_ids:
            fail(f"{material_id}: unknown category {material.get('category')!r}")
        compatible = material.get("compatible_types")
        if (
            not isinstance(compatible, list)
            or not compatible
            or any(item not in COMPONENT_TYPES or item == "other" for item in compatible)
            or len(set(compatible)) != len(compatible)
        ):
            fail(f"{material_id}: compatible_types must contain supported component types")
        if material.get("pricing_unit") not in _PRICING_UNITS:
            fail(f"{material_id}: pricing_unit must be sqft or rft")
        for field in ("default_material_rate", "default_labour_rate"):
            if not _finite_number(material.get(field)) or material[field] < 0:
                fail(f"{material_id}: {field} must be a non-negative number")
        wastage = material.get("default_wastage_pct")
        if not _finite_number(wastage) or not 0 <= wastage <= 50:
            fail(f"{material_id}: default_wastage_pct must be between 0 and 50")
        purchase_unit = material.get("purchase_unit")
        coverage = material.get("coverage_per_purchase_unit")
        if purchase_unit is not None and not _nonempty_string(purchase_unit):
            fail(f"{material_id}: purchase_unit must be a non-empty string or null")
        if (purchase_unit is None) != (coverage is None):
            fail(f"{material_id}: purchase_unit and coverage_per_purchase_unit must both be set or null")
        if coverage is not None and (not _finite_number(coverage) or coverage <= 0):
            fail(f"{material_id}: coverage_per_purchase_unit must be greater than zero")
        if not isinstance(material.get("swatch_hex"), str) or not _HEX_COLOR.fullmatch(material["swatch_hex"]):
            fail(f"{material_id}: swatch_hex must match #RRGGBB")
        description = material.get("prompt_description")
        if (
            not isinstance(description, str)
            or not 5 <= len(description) <= 200
            or any(char in description for char in '<>"\'{}')
        ):
            fail(f"{material_id}: prompt_description must be 5-200 plain visual characters")
        for field in ("maintenance_note", "durability_note"):
            if not isinstance(material.get(field), str) or len(material[field]) > 200:
                fail(f"{material_id}: {field} must be a string of at most 200 characters")
        for component_type in compatible:
            supported.add(component_type)
            previous = type_units.setdefault(component_type, material["pricing_unit"])
            if previous != material["pricing_unit"]:
                fail(f"{material_id}: pricing_unit conflicts for component type {component_type}")

    if not _REQUIRED_SUPPORTED_TYPES.issubset(supported):
        fail("at least one material must support wall, pillar, and railing")
    if set(data) - {"version", "categories", "materials"}:
        fail("only version, categories, and materials are allowed at the top level")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def catalogue_response(catalogue: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": catalogue["version"],
        "categories": catalogue["categories"],
        "materials": catalogue["materials"],
        "type_map": catalogue["type_map"],
    }


def materials_for_type(
    catalogue: Dict[str, Any], component_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    if component_type is None:
        return list(catalogue["materials"])
    ids = set(compatible_material_ids(component_type, catalogue))
    return [material for material in catalogue["materials"] if material["id"] in ids]


def get_material(catalogue: Dict[str, Any], material_id: str) -> Optional[Dict[str, Any]]:
    return next((item for item in catalogue["materials"] if item["id"] == material_id), None)


def is_compatible(
    catalogue: Dict[str, Any], material_id: str, component_type: str
) -> bool:
    return is_material_compatible(material_id, component_type, catalogue)


def allows_color(material: Dict[str, Any]) -> bool:
    return material["category"] in {"paint", "texture"}


def category_order(catalogue: Dict[str, Any]) -> List[str]:
    return [category["id"] for category in catalogue["categories"]]
