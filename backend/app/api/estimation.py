"""Measurement, rate, AI-assisted estimate, and estimate endpoints."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, status

from app.api.deps import get_catalogue, get_db, get_project, get_settings, get_storage
from app.core.config import Settings
from app.core.storage import StorageManager
from app.schemas.estimation import (
    AIEstimateRequest,
    AIEstimateResponse,
    EstimateResponse,
    EffectiveRateResponse,
    MeasurementListResponse,
    MeasurementResponse,
    MeasurementSet,
    RateListResponse,
    RateOverride,
)
from app.services import measurement_service

router = APIRouter(tags=["Estimation"])


@router.get(
    "/projects/{project_id}/measurements",
    response_model=MeasurementListResponse,
)
def list_measurements(
    project_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> MeasurementListResponse:
    return MeasurementListResponse(
        **measurement_service.list_measurements(conn, project_id)
    )


@router.put(
    "/projects/{project_id}/components/{component_id}/measurement",
    response_model=MeasurementResponse,
)
def set_measurement(
    project_id: str,
    component_id: str,
    payload: MeasurementSet,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> MeasurementResponse:
    return MeasurementResponse(
        **measurement_service.set_measurement(
            conn,
            project_id,
            component_id,
            payload.model_dump(),
            catalogue,
        )
    )


@router.delete(
    "/projects/{project_id}/components/{component_id}/measurement",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_measurement(
    project_id: str,
    component_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
) -> None:
    measurement_service.delete_measurement(conn, project_id, component_id)


@router.post(
    "/projects/{project_id}/measurements/ai-estimate",
    response_model=AIEstimateResponse,
)
def create_ai_estimates(
    project_id: str,
    payload: AIEstimateRequest,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: StorageManager = Depends(get_storage),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> AIEstimateResponse:
    return AIEstimateResponse(
        **measurement_service.create_ai_estimates(
            conn,
            settings,
            storage,
            project_id,
            catalogue,
            payload.model_dump(),
        )
    )


@router.get(
    "/projects/{project_id}/rates",
    response_model=RateListResponse,
)
def list_rates(
    project_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> RateListResponse:
    return RateListResponse(**measurement_service.list_rates(conn, project_id, catalogue))


@router.put(
    "/projects/{project_id}/rates/{material_id}",
    response_model=EffectiveRateResponse,
)
def set_rate(
    project_id: str,
    material_id: str,
    payload: RateOverride,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> EffectiveRateResponse:
    return EffectiveRateResponse(
        **measurement_service.set_rate(
            conn,
            project_id,
            material_id,
            payload.model_dump(exclude_unset=True),
            catalogue,
        )
    )


@router.delete(
    "/projects/{project_id}/rates/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_rate(
    project_id: str,
    material_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> None:
    measurement_service.delete_rate(conn, project_id, material_id, catalogue)


@router.get(
    "/projects/{project_id}/variants/{variant_id}/estimate",
    response_model=EstimateResponse,
)
def get_estimate(
    project_id: str,
    variant_id: str,
    _project: Dict[str, Any] = Depends(get_project),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    catalogue: Dict[str, Any] = Depends(get_catalogue),
) -> EstimateResponse:
    return EstimateResponse(
        **measurement_service.compute_variant_estimate(
            conn, project_id, variant_id, catalogue, settings.CURRENCY
        )
    )
