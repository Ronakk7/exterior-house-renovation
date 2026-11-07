"""Measurement, rate override, and cost estimation schemas."""

import math
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MeasurementSet(BaseModel):
    """Payload to record or update component dimensions."""

    input_mode: Literal["dimensions", "area", "length"]
    width_ft: Optional[float] = None
    height_ft: Optional[float] = None
    length_ft: Optional[float] = None
    area_sqft: Optional[float] = None
    deduction_sqft: float = Field(default=0.0, ge=0.0)
    uncertainty_pct: float = Field(default=15.0, ge=0.0, le=100.0)
    note: Optional[str] = Field(None, max_length=200)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "MeasurementSet":
        if self.input_mode == "dimensions":
            if (
                self.width_ft is None
                or not math.isfinite(self.width_ft)
                or self.width_ft <= 0
                or self.width_ft > 1000
            ):
                raise ValueError("width_ft must be positive and <= 1000 for dimensions mode")
            if (
                self.height_ft is None
                or not math.isfinite(self.height_ft)
                or self.height_ft <= 0
                or self.height_ft > 1000
            ):
                raise ValueError("height_ft must be positive and <= 1000 for dimensions mode")
        elif self.input_mode == "area":
            if (
                self.area_sqft is None
                or not math.isfinite(self.area_sqft)
                or self.area_sqft <= 0
                or self.area_sqft > 1000
            ):
                raise ValueError("area_sqft must be positive and <= 1000 for area mode")
        elif self.input_mode == "length":
            if (
                self.length_ft is None
                or not math.isfinite(self.length_ft)
                or self.length_ft <= 0
                or self.length_ft > 1000
            ):
                raise ValueError("length_ft must be positive and <= 1000 for length mode")
        else:
            raise ValueError(f"Invalid input_mode: {self.input_mode}")
        if not math.isfinite(self.deduction_sqft) or self.deduction_sqft < 0:
            raise ValueError("deduction_sqft must be a finite non-negative number")
        if not math.isfinite(self.uncertainty_pct):
            raise ValueError("uncertainty_pct must be finite")
        return self


class MeasurementResponse(BaseModel):
    """Component measurement record."""

    component_id: str
    input_mode: str
    width_ft: Optional[float] = None
    height_ft: Optional[float] = None
    length_ft: Optional[float] = None
    area_sqft: Optional[float] = None
    deduction_sqft: float = 0.0
    net_area_sqft: Optional[float] = None
    uncertainty_pct: float
    source: str
    note: Optional[str] = None
    updated_at: str


class MeasurementListResponse(BaseModel):
    """List of component measurements."""

    items: List[MeasurementResponse]


class AIEstimateRequest(BaseModel):
    """Payload to request AI-assisted approximate dimensions."""

    component_ids: Optional[List[str]] = None
    reference_note: Optional[str] = Field(None, max_length=200)
    floor_count: Optional[int] = Field(None, ge=1, le=6)

    model_config = ConfigDict(extra="forbid")


class AIEstimateEnvelope(BaseModel):
    """Strict model-response envelope; individual estimate records are checked separately."""

    estimates: List[Any]
    model_config = ConfigDict(extra="forbid")


class SkippedComponent(BaseModel):
    """Component skipped during AI estimation."""

    component_id: str
    reason: str


class AIEstimateResponse(BaseModel):
    """Results from an AI estimation operation."""

    stage_run_id: str
    items: List[MeasurementResponse]
    skipped: List[SkippedComponent] = Field(default_factory=list)
    disclaimer: str = (
        "AI-assisted visual estimates are approximate. Please check and edit them."
    )


class RateOverride(BaseModel):
    """Payload to override pricing rates for a material."""

    material_rate: Optional[float] = Field(None, ge=0.0, le=1_000_000)
    labour_rate: Optional[float] = Field(None, ge=0.0, le=1_000_000)
    wastage_pct: Optional[float] = Field(None, ge=0.0, le=50.0)

    model_config = ConfigDict(extra="forbid")


class DefaultRates(BaseModel):
    """Default rates from the catalogue."""

    material_rate: float
    labour_rate: float
    wastage_pct: float


class EffectiveRateResponse(BaseModel):
    """Material rate view showing active rate vs catalogue default."""

    material_id: str
    material_name: str
    pricing_unit: str
    material_rate: float
    labour_rate: float
    wastage_pct: float
    is_overridden: bool
    defaults: DefaultRates


class RateListResponse(BaseModel):
    """List of effective rates."""

    items: List[EffectiveRateResponse]


class MissingMeasurement(BaseModel):
    """Selected component lacking measurement inputs."""

    component_id: str
    component_label: str
    material_name: str


class LineItem(BaseModel):
    """Estimate calculation line item."""

    component_id: str
    component_type: str
    component_label: str
    material_id: str
    material_name: str
    category: str
    pricing_unit: str
    measure_value: float
    measure_unit: str
    wastage_pct: float
    quantity_with_wastage: float
    purchase_quantity: Optional[float] = None
    purchase_unit: Optional[str] = None
    material_cost: float
    labour_cost: float
    line_total: float
    low_total: float
    high_total: float
    measurement_source: str
    uncertainty_pct: float


class CategoryTotal(BaseModel):
    """Category subtotal."""

    category: str
    material_cost: float
    labour_cost: float
    total: float


class EstimateResponse(BaseModel):
    """Full computed cost and quantity estimate for a variant."""

    variant_id: str
    currency: str
    line_items: List[LineItem] = Field(default_factory=list)
    category_totals: List[CategoryTotal] = Field(default_factory=list)
    grand_total: float = 0.0
    grand_total_low: float = 0.0
    grand_total_high: float = 0.0
    missing_measurements: List[MissingMeasurement] = Field(default_factory=list)
    disclaimers: List[str] = Field(
        default_factory=lambda: [
            "Estimates are approximate and advisory, not a binding quotation."
        ]
    )
