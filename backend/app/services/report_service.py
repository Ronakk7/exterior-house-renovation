"""Report model assembly, report lifecycle, and secure PDF retrieval."""

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import transaction
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.ids import generate_id
from app.core.storage import StorageManager
from app.repositories import (
    component_repo,
    generation_repo,
    photo_repo,
    project_repo,
    report_repo,
    selection_repo,
    stage_run_repo,
    variant_repo,
)
from app.services import measurement_service, redesign_service
from app.services.pdf_renderer import project_slug, render_report_pdf

logger = logging.getLogger(__name__)

HOW_ESTIMATES_WERE_MADE = [
    "You tell the app how big each selected part is (width and height, or area, or length for railings). If you cannot, an optional AI can suggest approximate sizes from your photo; these are labelled and you can change them.",
    "The app subtracts openings (windows, doors) you enter to get the surface to be finished.",
    "For each material it adds a wastage allowance (default per material, editable) to get the quantity to buy, and also shows an approximate purchase quantity using the material's coverage.",
    "Cost is the material rate times quantity with wastage plus the labour rate times the installed surface, using editable rates.",
    "Each line shows a range based on the uncertainty of its measurement. Totals add up the lines.",
]

LIMITATIONS = [
    "The building is a residential low-rise building; only exterior renovation is considered; no structural engineering is included.",
    "Estimates are advisory, not a binding quotation.",
    "The redesigned image is an AI-generated preview. It is not a drawing, may differ from the real house in small details, and was not used for any measurement.",
    "Surface areas rely on approximate measurements entered by the homeowner or estimated by AI from a single photograph with no known scale.",
    "Perspective, hidden or curved surfaces are not modelled; overlapping regions may be counted twice if measured twice.",
    "Default rates and wastage allowances are placeholders; real prices differ by location, supplier and time.",
    "Exclusions: scaffolding, surface preparation, repairs, taxes, transport.",
    "Ranges are sums of per-line uncertainties, not statistical confidence intervals.",
    "Please verify all dimensions on site before ordering materials.",
]


def _get_variant(
    conn: sqlite3.Connection, project_id: str, variant_id: Optional[str]
) -> Dict[str, Any]:
    project = project_repo.get_by_id(conn, project_id)
    if project is None:
        raise NotFoundError("project")
    chosen_id = variant_id or project.get("active_variant_id")
    if not chosen_id:
        raise NotFoundError("variant")
    variant = variant_repo.get_by_id(conn, chosen_id, project_id)
    if variant is None:
        raise NotFoundError("variant")
    return variant


def _select_generation(
    conn: sqlite3.Connection,
    project_id: str,
    variant_id: str,
    generation_id: Optional[str],
    catalogue: Dict[str, Any],
    storage: StorageManager,
) -> Optional[Dict[str, Any]]:
    generation: Optional[Dict[str, Any]]
    if generation_id:
        generation = generation_repo.get_by_id(conn, generation_id, project_id)
        if generation is None or generation["variant_id"] != variant_id:
            raise NotFoundError("generation")
        if generation["status"] != "succeeded":
            raise ConflictError(
                details={"reason": "generation_not_succeeded"},
                message="The selected redesign generation has not succeeded.",
            )
    else:
        generations = generation_repo.list_by_project(conn, project_id, variant_id)
        succeeded = [item for item in generations if item["status"] == "succeeded"]
        generation = next((item for item in succeeded if item["is_approved"]), None)
        if generation is None and succeeded:
            generation = succeeded[0]
    if generation is None:
        return None
    if not generation.get("image_path"):
        logger.warning(
            "Report redesign generation has no image; using no-image placeholder",
            extra={"project_id": project_id, "generation_id": generation["id"]},
        )
        return None
    try:
        storage.get_file_path(generation["image_path"])
    except NotFoundError:
        logger.warning(
            "Report redesign image is missing; using no-image placeholder",
            extra={"project_id": project_id, "generation_id": generation["id"]},
        )
        return None

    generation_view = next(
        (
            item
            for item in redesign_service.list_generations(
                conn, project_id, catalogue, variant_id
            )["items"]
            if item["id"] == generation["id"]
        ),
        None,
    )
    return {
        **generation,
        "is_stale": bool(generation_view and generation_view["is_stale"]),
    }


def build_report_model(
    conn: sqlite3.Connection,
    storage: StorageManager,
    project_id: str,
    report_id: str,
    variant: Dict[str, Any],
    generation: Optional[Dict[str, Any]],
    catalogue: Dict[str, Any],
    currency: str,
) -> Dict[str, Any]:
    """Assemble all report facts without performing PDF rendering."""
    project = project_repo.get_by_id(conn, project_id)
    if project is None:
        raise NotFoundError("project")
    photos = photo_repo.list_by_project(conn, project_id)
    photo = next((item for item in photos if item["view_index"] == 1), None)
    if photo is None:
        raise AppError("NO_PHOTO", "Upload a photo before generating a report.", 409)
    original_path = photo["stored_path"]
    try:
        storage.get_file_path(original_path)
    except NotFoundError as exc:
        raise AppError(
            "INTERNAL_ERROR",
            "The original house photo is unavailable, so the report could not be created.",
            500,
        ) from exc

    estimate = measurement_service.compute_variant_estimate(
        conn, project_id, variant["id"], catalogue, currency
    )
    selections = selection_repo.list_by_variant(conn, variant["id"])
    components = {
        item["id"]: item for item in component_repo.list_by_project(conn, project_id)
    }
    materials = {item["id"]: item for item in catalogue["materials"]}
    categories = {item["id"]: item["name"] for item in catalogue["categories"]}
    ordered_component_ids: List[str] = []
    for line in estimate["line_items"]:
        if line["component_id"] not in ordered_component_ids:
            ordered_component_ids.append(line["component_id"])
    for missing in estimate["missing_measurements"]:
        if missing["component_id"] not in ordered_component_ids:
            ordered_component_ids.append(missing["component_id"])
    for component in component_repo.list_by_project(conn, project_id):
        if any(selection["component_id"] == component["id"] for selection in selections) and component["id"] not in ordered_component_ids:
            ordered_component_ids.append(component["id"])
    region_numbers = {
        component_id: index
        for index, component_id in enumerate(ordered_component_ids, start=1)
    }

    materials_table: List[Dict[str, Any]] = []
    material_notes: List[Dict[str, Any]] = []
    seen_material_ids = set()
    regions: List[Dict[str, Any]] = []
    for selection in selections:
        component = components.get(selection["component_id"])
        material = materials.get(selection["material_id"])
        if component is None or material is None:
            continue
        params = selection.get("params") or {}
        color = params.get("color", material["name"])
        color_hex = params.get("color_hex")
        materials_table.append({
            "number": region_numbers[component["id"]],
            "component_id": component["id"],
            "label": component["label"],
            "type": component["type"],
            "material_id": material["id"],
            "material_name": material["name"],
            "category": material["category"],
            "category_name": categories.get(material["category"], material["category"]),
            "color": color,
            "color_hex": color_hex,
            "note": params.get("note"),
        })
        regions.append({
            "number": region_numbers[component["id"]],
            "id": component["id"],
            "type": component["type"],
            "label": component["label"],
            "box_x": component["box_x"],
            "box_y": component["box_y"],
            "box_w": component["box_w"],
            "box_h": component["box_h"],
        })
        if material["id"] not in seen_material_ids:
            material_notes.append({
                "id": material["id"],
                "name": material["name"],
                "maintenance_note": material["maintenance_note"],
                "durability_note": material["durability_note"],
            })
            seen_material_ids.add(material["id"])

    rate_by_id = {
        item["material_id"]: item
        for item in measurement_service.list_rates(conn, project_id, catalogue)["items"]
    }
    used_material_ids = []
    for line in estimate["line_items"]:
        if line["material_id"] not in used_material_ids:
            used_material_ids.append(line["material_id"])
    rates = [
        {
            "material_id": material_id,
            "material_name": rate_by_id[material_id]["material_name"],
            "pricing_unit": rate_by_id[material_id]["pricing_unit"],
            "material_rate": rate_by_id[material_id]["material_rate"],
            "labour_rate": rate_by_id[material_id]["labour_rate"],
            "wastage_pct": rate_by_id[material_id]["wastage_pct"],
            "is_overridden": rate_by_id[material_id]["is_overridden"],
        }
        for material_id in used_material_ids
    ]
    quantities: List[Dict[str, Any]] = []
    cost_lines: List[Dict[str, Any]] = []
    for line in estimate["line_items"]:
        number = region_numbers[line["component_id"]]
        quantities.append({**line, "number": number})
        cost_lines.append({**line, "number": number})
    missing = [
        {
            **item,
            "number": region_numbers[item["component_id"]],
            "label": components.get(item["component_id"], {}).get("label", item["component_label"]),
        }
        for item in estimate["missing_measurements"]
    ]
    category_costs = [
        {
            **item,
            "category_name": categories.get(item["category"], item["category"]),
        }
        for item in estimate["category_totals"]
    ]

    redesign_status = "none"
    status_text = "No redesigned image was generated for this design."
    image_path = None
    if generation is not None:
        image_path = generation["image_path"]
        if generation["is_stale"]:
            redesign_status = "outdated"
            status_text = "AI-generated preview. OUTDATED: materials or regions were changed after this image was created."
        elif generation["is_approved"]:
            redesign_status = "approved"
            status_text = "AI-generated preview. Approved by the homeowner."
        else:
            redesign_status = "unapproved"
            status_text = "AI-generated preview. Not yet reviewed or approved."

    conditional_notes: List[str] = []
    if any(item["measurement_source"] == "ai_estimate" for item in estimate["line_items"]):
        conditional_notes.append(
            "Measurements marked AI estimate come from an AI reading of the photo and may be inaccurate by 25% or more."
        )
    if missing:
        conditional_notes.append(
            "The regions listed under Not included have no measurement and are excluded from totals."
        )
    if any(not item["is_overridden"] for item in rates):
        conditional_notes.append("Rates marked default are placeholders, not market prices.")
    if redesign_status == "outdated":
        conditional_notes.append(status_text)

    return {
        "report_id": report_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "project": {"id": project["id"], "name": project["name"]},
        "variant": {"id": variant["id"], "name": variant["name"]},
        "photos": {
            "original_path": original_path,
            "width_px": photo["width_px"],
            "height_px": photo["height_px"],
        },
        "redesign": {
            "id": generation["id"] if generation else None,
            "status": redesign_status,
            "status_text": status_text,
            "image_path": image_path,
        },
        "estimate": estimate,
        "summary": {
            "regions": len(selections),
            "user_measurements": sum(
                item["measurement_source"] == "user" for item in estimate["line_items"]
            ),
            "ai_measurements": sum(
                item["measurement_source"] == "ai_estimate" for item in estimate["line_items"]
            ),
            "missing_measurements": len(missing),
        },
        "materials": materials_table,
        "material_notes": material_notes,
        "regions": regions,
        "quantities": quantities,
        "costs": {"lines": cost_lines, "categories": category_costs},
        "rates": rates,
        "missing_measurements": missing,
        "limitations": LIMITATIONS + conditional_notes,
        "how_estimates_were_made": HOW_ESTIMATES_WERE_MADE,
        "disclaimers": estimate["disclaimers"],
    }


def _report_response(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "variant_id": row["variant_id"],
        "generation_id": row["generation_id"],
        "grand_total": row["grand_total"],
        "currency": row["currency"],
        "download_url": f"/api/projects/{row['project_id']}/reports/{row['id']}/download",
        "created_at": row["created_at"],
    }


def create_report(
    conn: sqlite3.Connection,
    storage: StorageManager,
    project_id: str,
    variant_id: Optional[str],
    generation_id: Optional[str],
    catalogue: Dict[str, Any],
    currency: str,
) -> Dict[str, Any]:
    """Validate, render, and persist one immutable report with cleanup on failure."""
    project = project_repo.get_by_id(conn, project_id)
    if project is None:
        raise NotFoundError("project")
    variant = _get_variant(conn, project_id, variant_id)
    if not photo_repo.list_by_project(conn, project_id):
        raise AppError("NO_PHOTO", "Upload a photo before generating a report.", 409)
    if selection_repo.count_by_variant(conn, variant["id"]) == 0:
        raise AppError("NO_SELECTIONS", "Choose at least one material before generating a report.", 409)
    generation = _select_generation(
        conn, project_id, variant["id"], generation_id, catalogue, storage
    )

    report_id = generate_id("rep")
    started = time.monotonic()
    with transaction(conn, immediate=True):
        run = stage_run_repo.create(conn, project_id, "report")
    saved_path: Optional[str] = None
    try:
        model = build_report_model(
            conn,
            storage,
            project_id,
            report_id,
            variant,
            generation,
            catalogue,
            currency,
        )
        pdf = render_report_pdf(model, storage)
        saved_path = storage.project_path(project_id, "reports", f"{report_id}.pdf")
        storage.save_bytes(saved_path, pdf)
        with transaction(conn, immediate=True):
            report = report_repo.create(
                conn,
                project_id,
                variant["id"],
                generation["id"] if generation else None,
                saved_path,
                model["estimate"]["grand_total"],
                model["estimate"]["currency"],
                report_id=report_id,
            )
            stage_run_repo.update_completed(
                conn,
                run["id"],
                "succeeded",
                detail={"report_id": report_id},
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            project_repo.touch_updated_at(conn, project_id)
        return _report_response(report)
    except Exception as exc:
        if saved_path:
            try:
                storage.delete_file(saved_path)
            except OSError:
                logger.warning(
                    "Could not remove partial report file",
                    extra={"project_id": project_id, "report_id": report_id},
                    exc_info=True,
                )
        try:
            with transaction(conn, immediate=True):
                if stage_run_repo.get_by_id(conn, run["id"]) is not None:
                    stage_run_repo.update_completed(
                        conn,
                        run["id"],
                        "failed",
                        error_code=exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR",
                        error_message=exc.message if isinstance(exc, AppError) else "Report generation failed.",
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
        except Exception:
            logger.exception(
                "Could not record report stage failure",
                extra={"project_id": project_id, "report_id": report_id},
            )
        if isinstance(exc, AppError):
            raise
        logger.exception(
            "Report generation failed",
            extra={"project_id": project_id, "report_id": report_id},
        )
        raise AppError(
            "INTERNAL_ERROR",
            "We could not create the report. Please try again.",
            500,
        ) from exc


def list_reports(conn: sqlite3.Connection, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "items": [
            _report_response(row)
            for row in report_repo.list_by_project(conn, project_id)
        ]
    }


def get_report_download(
    conn: sqlite3.Connection,
    storage: StorageManager,
    project_id: str,
    report_id: str,
) -> Tuple[bytes, str]:
    report = report_repo.get_by_id(conn, report_id, project_id)
    if report is None:
        raise NotFoundError("report")
    try:
        pdf = storage.read_bytes(report["pdf_path"])
    except NotFoundError as exc:
        raise NotFoundError("report", "The report file is missing.") from exc
    project = project_repo.get_by_id(conn, project_id)
    slug = project_slug(project["name"] if project else "project")
    return pdf, f'renovation-report-{slug}.pdf'
