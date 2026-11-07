"""Read-only material compatibility lookup for component types."""

from typing import Any, Dict, Iterable, Set


def supported_component_types(catalogue: Dict[str, Any]) -> Set[str]:
    """Return component types compatible with at least one catalogue material."""
    supported: Set[str] = set()
    for material in catalogue.get("materials", []):
        compatible_types = material.get("compatible_types", [])
        if isinstance(compatible_types, Iterable) and not isinstance(
            compatible_types, (str, bytes)
        ):
            supported.update(
                component_type
                for component_type in compatible_types
                if isinstance(component_type, str)
            )
    return supported


def is_component_type_supported(
    component_type: str, catalogue: Dict[str, Any]
) -> bool:
    """Check support against the startup-loaded, read-only catalogue."""
    return component_type in supported_component_types(catalogue)


def compatible_material_ids(
    component_type: str, catalogue: Dict[str, Any]
) -> list[str]:
    """Return read-only material IDs compatible with one component type."""
    return [
        material["id"]
        for material in catalogue.get("materials", [])
        if isinstance(material.get("id"), str)
        and component_type in material.get("compatible_types", [])
    ]


def is_material_compatible(
    material_id: str, component_type: str, catalogue: Dict[str, Any]
) -> bool:
    """Check material compatibility through the shared catalogue lookup."""
    return material_id in compatible_material_ids(component_type, catalogue)
