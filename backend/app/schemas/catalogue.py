"""Material catalogue request and response schemas."""

from typing import Dict, List, Optional
from pydantic import BaseModel


class CategoryInfo(BaseModel):
    """Catalogue material category."""

    id: str
    name: str


class MaterialResponse(BaseModel):
    """Catalogue material item."""

    id: str
    name: str
    category: str
    compatible_types: List[str]
    pricing_unit: str
    purchase_unit: Optional[str] = None
    coverage_per_purchase_unit: Optional[float] = None
    default_material_rate: float
    default_labour_rate: float
    default_wastage_pct: float
    swatch_hex: str
    prompt_description: str
    maintenance_note: str
    durability_note: str


class CatalogueResponse(BaseModel):
    """Full material catalogue with type mapping."""

    version: str
    categories: List[CategoryInfo]
    materials: List[MaterialResponse]
    type_map: Dict[str, List[str]]


class MaterialListResponse(BaseModel):
    """List of catalogue materials."""

    items: List[MaterialResponse]

