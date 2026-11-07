"""Read-only material catalogue routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_catalogue as get_catalogue_dependency
from app.schemas.catalogue import (
    CatalogueResponse,
    MaterialListResponse,
)
from app.schemas.common import COMPONENT_TYPES
from app.services import catalogue_service
from app.core.errors import ValidationAppError

router = APIRouter(prefix="/catalogue", tags=["Catalogue"])


@router.get("", response_model=CatalogueResponse)
def get_catalogue(
    response: Response,
    catalogue: Dict[str, Any] = Depends(get_catalogue_dependency),
) -> CatalogueResponse:
    response.headers["Cache-Control"] = "public, max-age=300"
    return CatalogueResponse(**catalogue_service.catalogue_response(catalogue))


@router.get("/materials", response_model=MaterialListResponse)
def get_materials(
    component_type: Optional[str] = Query(None),
    catalogue: Dict[str, Any] = Depends(get_catalogue_dependency),
) -> MaterialListResponse:
    if component_type is not None and component_type not in COMPONENT_TYPES:
        raise ValidationAppError(
            "Unknown component type.",
            {"fields": [{"field": "component_type", "problem": "unknown component type"}]},
        )
    return MaterialListResponse(
        items=catalogue_service.materials_for_type(catalogue, component_type)
    )
