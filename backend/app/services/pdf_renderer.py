"""ReportLab PDF rendering and report-specific image preparation."""

import logging
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image as ReportImage,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.storage import StorageManager

logger = logging.getLogger(__name__)
_ACCENT = colors.HexColor("#234e70")
_AMBER = colors.HexColor("#fff2cc")
_BOX_COLOURS = {
    "wall": "#e66b25",
    "window": "#2878b5",
    "door": "#7e57c2",
    "balcony": "#239a78",
    "railing": "#d34d66",
    "pillar": "#8c6d31",
    "parapet": "#397b87",
    "gate": "#6a994e",
    "roof_edge": "#c05299",
    "other": "#666666",
}


def sanitize_pdf_text(value: Any) -> str:
    """Replace characters unavailable in the built-in Latin-1 fonts."""
    text = str(value if value is not None else "")
    return text.encode("latin-1", errors="replace").decode("latin-1")


def format_currency(value: Any, currency: str) -> str:
    """Format currency with Indian digit grouping for INR."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{abs(amount):,.2f}"
    if currency.upper() == "INR":
        integer, fraction = formatted.split(".")
        digits = integer.replace(",", "")
        if len(digits) > 3:
            integer = digits[-3:]
            digits = digits[:-3]
            groups = []
            while digits:
                groups.insert(0, digits[-2:])
                digits = digits[:-2]
            integer = ",".join(groups + [integer])
        else:
            integer = digits
        formatted = f"{integer}.{fraction}"
    if amount < 0:
        formatted = f"-{formatted}"
    return f"{currency.upper()} {formatted}"


def project_slug(name: str) -> str:
    """Build the bounded ASCII slug used in report download filenames."""
    value = unicodedata.normalize("NFKD", sanitize_pdf_text(name)).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    value = re.sub(r"-+", "-", value)[:40].strip("-")
    return value or "project"


def _prepared_image(storage: StorageManager, path: str, max_side: int) -> bytes:
    raw = storage.read_bytes(path)
    try:
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Stored report image could not be decoded: {path}") from exc
    scale = min(1.0, max_side / max(image.size))
    if scale < 1:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    output = BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True, exif=b"")
    return output.getvalue()


def _region_map(
    original: bytes, regions: List[Dict[str, Any]], max_side: int
) -> bytes:
    with Image.open(BytesIO(original)) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for region in regions:
        x = round(region["box_x"] * image.width)
        y = round(region["box_y"] * image.height)
        right = round((region["box_x"] + region["box_w"]) * image.width)
        bottom = round((region["box_y"] + region["box_h"]) * image.height)
        colour = _BOX_COLOURS.get(region["type"], _BOX_COLOURS["other"])
        draw.rectangle((x, y, right, bottom), outline=colour, width=max(2, image.width // 400))
        label = str(region["number"])
        bounds = draw.textbbox((0, 0), label, font=font)
        label_width = bounds[2] - bounds[0] + 8
        label_height = bounds[3] - bounds[1] + 6
        draw.rectangle((x, y, x + label_width, y + label_height), fill=colour)
        draw.text((x + 4, y + 2), label, fill="white", font=font)
    scale = min(1.0, max_side / max(image.size))
    if scale < 1:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    output = BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


from reportlab.pdfgen.canvas import Canvas


class NumberedCanvas(Canvas):
    """Draw total page count after all pages have been laid out."""

    def __init__(self, *args: Any, report_model: Dict[str, Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.report_model = report_model
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(self._pageNumber, total)
            Canvas.showPage(self)
        Canvas.save(self)

    def _draw_footer(self, page: int, total: int) -> None:
        width, _ = A4
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#555555"))
        self.drawString(18 * mm, 10 * mm, "Advisory estimate - not a quotation")
        self.drawCentredString(width / 2, 10 * mm, self.report_model["project"]["id"][:12])
        self.drawRightString(width - 18 * mm, 10 * mm, f"Page {page} of {total}")
        self.restoreState()


class _Placeholder(Flowable):
    def __init__(self, text: str, width: float, height: float = 112) -> None:
        super().__init__()
        self.text = text
        self.width = width
        self.height = height

    def draw(self) -> None:
        self.canv.setStrokeColor(colors.HexColor("#b8c2cc"))
        self.canv.setFillColor(colors.HexColor("#f4f6f8"))
        self.canv.roundRect(0, 0, self.width, self.height, 5, fill=1, stroke=1)
        self.canv.setFillColor(colors.HexColor("#4a5560"))
        self.canv.setFont("Helvetica", 9)
        self.canv.drawCentredString(self.width / 2, self.height / 2, self.text[:100])


class _ColourSwatch(Flowable):
    def __init__(self, value: str) -> None:
        super().__init__()
        self.value = value
        self.width = 12 * mm
        self.height = 5 * mm

    def draw(self) -> None:
        self.canv.setFillColor(colors.HexColor(self.value))
        self.canv.setStrokeColor(colors.HexColor("#777777"))
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=1)


def _paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    from xml.sax.saxutils import escape

    safe = escape(sanitize_pdf_text(text)).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _table(
    rows: List[List[Any]],
    widths: List[float],
    header: bool = True,
    right_columns: Optional[List[int]] = None,
) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ccd3da")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])
    if right_columns:
        for column in right_columns:
            commands.append(("ALIGN", (column, 1 if header else 0), (column, -1), "RIGHT"))
    table.setStyle(TableStyle(commands))
    return table


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=_ACCENT, alignment=TA_LEFT, spaceAfter=5),
        "h1": ParagraphStyle("ReportH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=_ACCENT, spaceBefore=5, spaceAfter=7),
        "h2": ParagraphStyle("ReportH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=_ACCENT, spaceBefore=6, spaceAfter=5),
        "body": ParagraphStyle("ReportBody", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12, spaceAfter=4),
        "small": ParagraphStyle("ReportSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9.5),
        "cell": ParagraphStyle("ReportCell", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9),
        "cell_right": ParagraphStyle("ReportCellRight", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9, alignment=TA_RIGHT),
        "caption": ParagraphStyle("ReportCaption", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER, textColor=colors.HexColor("#4a5560")),
        "summary": ParagraphStyle("ReportSummary", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=_ACCENT),
    }


def _image_flowable(data: bytes, max_width: float, max_height: float) -> ReportImage:
    with Image.open(BytesIO(data)) as image:
        width, height = image.size
    scale = min(max_width / width, max_height / height)
    return ReportImage(BytesIO(data), width=width * scale, height=height * scale)


def _build_story(
    model: Dict[str, Any],
    storage: StorageManager,
    max_side: int,
) -> List[Flowable]:
    styles = _styles()
    story: List[Flowable] = []
    page_width = A4[0] - 36 * mm
    original = _prepared_image(storage, model["photos"]["original_path"], max_side)
    redesign_data = None
    if model["redesign"]["image_path"]:
        try:
            redesign_data = _prepared_image(storage, model["redesign"]["image_path"], max_side)
        except Exception:
            logger.warning(
                "Report redesign image could not be prepared; using placeholder",
                extra={"report_id": model["report_id"], "generation_id": model["redesign"]["id"]},
                exc_info=True,
            )

    story.append(_paragraph("Exterior Renovation Plan", styles["title"]))
    story.append(_paragraph(model["project"]["name"], styles["h1"]))
    story.append(_paragraph(
        f"Design: {model['variant']['name']}  Generated {model['generated_at']} UTC "
        f"  Report {model['report_id'][-8:]}",
        styles["body"],
    ))
    summary = (
        f"Approx. {format_currency(model['estimate']['grand_total'], model['estimate']['currency'])}"
        f"\nRange: {format_currency(model['estimate']['grand_total_low'], model['estimate']['currency'])}"
        f" - {format_currency(model['estimate']['grand_total_high'], model['estimate']['currency'])}"
        f"\n{model['summary']['regions']} regions with materials; "
        f"{model['summary']['user_measurements']} user measurements; "
        f"{model['summary']['ai_measurements']} AI estimates; "
        f"{model['summary']['missing_measurements']} missing measurements"
    )
    summary_table = Table([[_paragraph(summary, styles["summary"])]], colWidths=[page_width])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf4f8")),
        ("BOX", (0, 0), (-1, -1), 0.8, _ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 7 * mm))

    image_gap = 5 * mm
    image_width = (page_width - image_gap) / 2
    image_height = 54 * mm
    original_flowable = _image_flowable(original, image_width, image_height)
    if redesign_data:
        redesign_flowable: Flowable = _image_flowable(redesign_data, image_width, image_height)
    else:
        redesign_flowable = _Placeholder(
            "No redesigned image was generated for this design.",
            image_width,
            image_height,
        )
    if model["photos"]["height_px"] > model["photos"]["width_px"] * 1.15:
        images = [[original_flowable], [_paragraph("Original house photo", styles["caption"])],
                  [redesign_flowable], [_paragraph(model["redesign"]["status_text"], styles["caption"])]]
        story.append(_table(images, [page_width], header=False))
    else:
        images = [[original_flowable, redesign_flowable],
                  [_paragraph("Original house photo", styles["caption"]),
                   _paragraph(model["redesign"]["status_text"], styles["caption"])]]
        story.append(_table(images, [image_width, image_width], header=False))
    if redesign_data:
        story.append(_paragraph(
            "AI-generated image. Colours, textures and details can differ from real materials.",
            styles["small"],
        ))

    story.append(PageBreak())
    story.append(_paragraph("Region map", styles["h1"]))
    try:
        region_map = _region_map(original, model["regions"], max_side)
        story.append(_image_flowable(region_map, page_width, 95 * mm))
    except Exception:
        logger.warning(
            "Report region map could not be drawn",
            extra={"report_id": model["report_id"]},
            exc_info=True,
        )
        story.append(_paragraph("Region map could not be prepared.", styles["small"]))

    story.append(_paragraph("Selected materials", styles["h1"]))
    material_rows: List[List[Any]] = [[
        "Region", "Label / type", "Material / category", "Colour", "Note"
    ]]
    for item in model["materials"]:
        material_rows.append([
            str(item["number"]),
            _paragraph(f"{item['label'][:60]}\n{item['type']}", styles["cell"]),
            _paragraph(f"{item['material_name']}\n{item['category_name']}", styles["cell"]),
            (
                Table(
                    [[_ColourSwatch(item["color_hex"])],
                     [_paragraph(item["color_hex"], styles["cell"])]],
                    colWidths=[30 * mm],
                )
                if item["color_hex"] and re.fullmatch(r"#[0-9A-Fa-f]{6}", item["color_hex"])
                else _paragraph(item["color"], styles["cell"])
            ),
            _paragraph(item["note"] or "", styles["cell"]),
        ])
    story.append(_table(
        material_rows,
        [13 * mm, 39 * mm, 44 * mm, 30 * mm, page_width - 126 * mm],
    ))
    story.append(_paragraph("Material notes", styles["h2"]))
    note_rows: List[List[Any]] = [["Material", "Maintenance", "Durability"]]
    note_rows.extend([
        [_paragraph(item["name"], styles["cell"]),
         _paragraph(item["maintenance_note"], styles["cell"]),
         _paragraph(item["durability_note"], styles["cell"])]
        for item in model["material_notes"]
    ])
    story.append(_table(note_rows, [45 * mm, 63 * mm, page_width - 108 * mm]))

    story.append(PageBreak())
    story.append(_paragraph("Quantities", styles["h1"]))
    quantity_rows: List[List[Any]] = [[
        "Region", "Material", "Measure", "Wastage", "Quantity", "Purchase", "Source"
    ]]
    for item in model["quantities"]:
        quantity_rows.append([
            str(item["number"]),
            _paragraph(item["material_name"][:60], styles["cell"]),
            f"{item['measure_value']:.2f} {item['measure_unit']}",
            f"{item['wastage_pct']:.2f}%",
            f"{item['quantity_with_wastage']:.2f} {item['measure_unit']}",
            (
                f"approx. {item['purchase_quantity']} {item['purchase_unit']}"
                if item["purchase_quantity"] is not None else "-"
            ),
            "AI estimate" if item["measurement_source"] == "ai_estimate" else "Your value",
        ])
    story.append(_table(quantity_rows, [
        11 * mm, 37 * mm, 27 * mm, 19 * mm, 34 * mm, 27 * mm, page_width - 155 * mm
    ]))
    story.append(_paragraph("Cost breakdown", styles["h1"]))
    cost_rows: List[List[Any]] = [[
        "Region / material", "Material", "Labour", "Line total", "Range"
    ]]
    for item in model["costs"]["lines"]:
        currency = model["estimate"]["currency"]
        cost_rows.append([
            _paragraph(f"{item['number']}. {item['component_label'][:60]}\n{item['material_name']}", styles["cell"]),
            format_currency(item["material_cost"], currency),
            format_currency(item["labour_cost"], currency),
            format_currency(item["line_total"], currency),
            _paragraph(
                f"{format_currency(item['low_total'], currency)}\n- {format_currency(item['high_total'], currency)}",
                styles["cell_right"],
            ),
        ])
    for category in model["costs"]["categories"]:
        cost_rows.append([
            _paragraph(f"{category['category_name']} subtotal", styles["cell"]),
            format_currency(category["material_cost"], model["estimate"]["currency"]),
            format_currency(category["labour_cost"], model["estimate"]["currency"]),
            format_currency(category["total"], model["estimate"]["currency"]),
            "",
        ])
    cost_rows.append([
        _paragraph("Approx. grand total", styles["cell"]),
        "", "",
        format_currency(model["estimate"]["grand_total"], model["estimate"]["currency"]),
        _paragraph(
            f"{format_currency(model['estimate']['grand_total_low'], model['estimate']['currency'])}\n- "
            f"{format_currency(model['estimate']['grand_total_high'], model['estimate']['currency'])}",
            styles["cell_right"],
        ),
    ])
    story.append(_table(cost_rows, [
        page_width * 0.35, page_width * 0.15, page_width * 0.15,
        page_width * 0.17, page_width * 0.18,
    ]))
    story.append(_paragraph("Rates used", styles["h1"]))
    rate_rows: List[List[Any]] = [[
        "Material", "Material rate", "Labour rate", "Wastage", "Rate source"
    ]]
    rate_rows.extend([
        [
            _paragraph(item["material_name"], styles["cell"]),
            f"{format_currency(item['material_rate'], model['estimate']['currency'])}/{item['pricing_unit']}",
            f"{format_currency(item['labour_rate'], model['estimate']['currency'])}/{item['pricing_unit']}",
            f"{item['wastage_pct']:.2f}%",
            "edited" if item["is_overridden"] else "default",
        ]
        for item in model["rates"]
    ])
    story.append(_table(rate_rows, [page_width * 0.28, page_width * 0.24, page_width * 0.22, page_width * 0.13, page_width * 0.13]))
    story.append(_paragraph("Not included", styles["h1"]))
    if model["missing_measurements"]:
        for missing in model["missing_measurements"]:
            story.append(_paragraph(
                f"Region {missing['number']}: {missing['label'][:60]} - {missing['material_name']}",
                styles["body"],
            ))
    else:
        story.append(_paragraph("All selected regions have usable measurements.", styles["body"]))

    story.append(PageBreak())
    story.append(_paragraph("How these estimates were made", styles["h1"]))
    for point in model["how_estimates_were_made"]:
        story.append(_paragraph(f"- {point}", styles["body"]))
    story.append(_paragraph("Assumptions and limitations", styles["h1"]))
    for note in model["limitations"]:
        story.append(_paragraph(f"- {note}", styles["body"]))
    story.append(_paragraph("Disclaimers", styles["h1"]))
    for disclaimer in model["disclaimers"]:
        story.append(_paragraph(f"- {disclaimer}", styles["body"]))
    return story


def _render_once(
    model: Dict[str, Any],
    storage: StorageManager,
    max_side: int,
) -> bytes:
    output = BytesIO()
    page_width, page_height = A4
    frame = Frame(
        18 * mm,
        18 * mm,
        page_width - 36 * mm,
        page_height - 36 * mm,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="normal",
    )
    template = PageTemplate(id="report", frames=[frame])
    document = BaseDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=sanitize_pdf_text("Exterior Renovation Plan"),
        author="Exterior House Renovation",
        pageTemplates=[template],
    )
    def make_canvas(*args: Any, **kwargs: Any) -> NumberedCanvas:
        kwargs["pageCompression"] = 0
        return NumberedCanvas(*args, report_model=model, **kwargs)

    document.build(
        _build_story(model, storage, max_side),
        canvasmaker=make_canvas,
    )
    return output.getvalue()


def render_report_pdf(model: Dict[str, Any], storage: StorageManager) -> bytes:
    """Render a report model to an A4 PDF, reducing images if needed."""
    pdf = _render_once(model, storage, 1600)
    if len(pdf) > 8 * 1024 * 1024:
        pdf = _render_once(model, storage, 1200)
    return pdf
