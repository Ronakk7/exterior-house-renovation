"""Pure Decimal-based quantity and cost calculations."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional


_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _number(value: Decimal) -> float:
    return float(_money(value))


def compute_estimate(
    variant_id: str,
    currency: str,
    selections: Iterable[Dict[str, Any]],
    components: Dict[str, Dict[str, Any]],
    measurements: Dict[str, Dict[str, Any]],
    materials: Dict[str, Dict[str, Any]],
    effective_rates: Dict[str, Dict[str, Any]],
    categories: List[str],
) -> Dict[str, Any]:
    """Compute estimate output from plain records without I/O or persistence."""
    line_items: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    category_values: Dict[str, Dict[str, Decimal]] = {}
    uses_ai_measurement = False
    uses_default_rate = False

    ordered_selections = sorted(
        selections,
        key=lambda item: (
            components.get(item["component_id"], {}).get("created_at", ""),
            item["component_id"],
        ),
    )
    for selection in ordered_selections:
        component_id = selection["component_id"]
        component = components.get(component_id)
        material = materials.get(selection["material_id"])
        if component is None or material is None:
            continue
        measurement = measurements.get(component_id)
        expected_unit = material["pricing_unit"]
        compatible_mode = (
            measurement is not None
            and (
                (expected_unit == "sqft" and measurement["input_mode"] in {"dimensions", "area"})
                or (expected_unit == "rft" and measurement["input_mode"] == "length")
            )
        )
        if not compatible_mode:
            missing.append(
                {
                    "component_id": component_id,
                    "component_label": component["label"],
                    "material_name": material["name"],
                }
            )
            continue

        measure = (
            _decimal(measurement["length_ft"])
            if expected_unit == "rft"
            else max(
                Decimal("0"),
                _decimal(measurement["area_sqft"])
                - _decimal(measurement.get("deduction_sqft") or 0),
            )
        )
        rate = effective_rates[material["id"]]
        wastage_pct = _decimal(rate["wastage_pct"])
        material_rate = _decimal(rate["material_rate"])
        labour_rate = _decimal(rate["labour_rate"])
        quantity = measure * (Decimal("1") + wastage_pct / Decimal("100"))
        material_cost = _money(quantity * material_rate)
        labour_cost = _money(measure * labour_rate)
        line_total = material_cost + labour_cost
        uncertainty = _decimal(measurement["uncertainty_pct"])
        low_total = _money(line_total * (Decimal("1") - uncertainty / Decimal("100")))
        high_total = _money(line_total * (Decimal("1") + uncertainty / Decimal("100")))
        coverage = material.get("coverage_per_purchase_unit")
        purchase_quantity: Optional[int] = None
        if coverage is not None and material.get("purchase_unit"):
            purchase_quantity = int(
                (quantity / _decimal(coverage)).to_integral_value(rounding=ROUND_CEILING)
            )

        line_items.append(
            {
                "component_id": component_id,
                "component_type": component["type"],
                "component_label": component["label"],
                "material_id": material["id"],
                "material_name": material["name"],
                "category": material["category"],
                "pricing_unit": expected_unit,
                "measure_value": _number(measure),
                "measure_unit": "sqft" if expected_unit == "sqft" else "ft",
                "wastage_pct": float(wastage_pct),
                "quantity_with_wastage": _number(quantity),
                "purchase_quantity": purchase_quantity,
                "purchase_unit": material.get("purchase_unit"),
                "material_cost": _number(material_cost),
                "labour_cost": _number(labour_cost),
                "line_total": _number(line_total),
                "low_total": _number(low_total),
                "high_total": _number(high_total),
                "measurement_source": measurement["source"],
                "uncertainty_pct": float(uncertainty),
            }
        )
        totals = category_values.setdefault(
            material["category"],
            {"material_cost": _ZERO, "labour_cost": _ZERO, "total": _ZERO},
        )
        totals["material_cost"] += material_cost
        totals["labour_cost"] += labour_cost
        totals["total"] += line_total
        uses_ai_measurement = uses_ai_measurement or measurement["source"] == "ai_estimate"
        uses_default_rate = uses_default_rate or not rate["is_overridden"]

    category_totals = [
        {
            "category": category,
            "material_cost": _number(category_values[category]["material_cost"]),
            "labour_cost": _number(category_values[category]["labour_cost"]),
            "total": _number(category_values[category]["total"]),
        }
        for category in categories
        if category in category_values
    ]
    grand_total = sum((_decimal(item["line_total"]) for item in line_items), _ZERO)
    grand_low = sum((_decimal(item["low_total"]) for item in line_items), _ZERO)
    grand_high = sum((_decimal(item["high_total"]) for item in line_items), _ZERO)
    disclaimers = [
        "Estimates are approximate and advisory, not a binding quotation."
    ]
    if uses_ai_measurement:
        disclaimers.append(
            "Some measurements are AI-assisted visual estimates and may be inaccurate. Please verify them on site."
        )
    if missing:
        disclaimers.append(
            "Some selected regions have no usable measurement and are not included in the totals."
        )
    if uses_default_rate:
        disclaimers.append(
            "Default rates are placeholder values. Replace them with quotes from your contractor or supplier."
        )
    disclaimers.append(
        "Surface areas come from approximate measurements, not from the photo alone. Ranges show the uncertainty you or the AI entered."
    )
    return {
        "variant_id": variant_id,
        "currency": currency,
        "line_items": line_items,
        "category_totals": category_totals,
        "grand_total": _number(grand_total),
        "grand_total_low": _number(grand_low),
        "grand_total_high": _number(grand_high),
        "missing_measurements": missing,
        "disclaimers": disclaimers,
    }
