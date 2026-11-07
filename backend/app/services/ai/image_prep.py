"""Build in-memory, orientation-corrected working images for AI requests."""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings

WORKING_JPEG_QUALITY = 85


@dataclass(frozen=True)
class WorkingImage:
    bytes: bytes
    mime_type: str
    width_px: int
    height_px: int
    scale_factor: float


def prepare_working_image(image_bytes: bytes, settings: Settings) -> WorkingImage:
    """Orient, flatten, downscale, and metadata-strip an image in memory."""
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            oriented = ImageOps.exif_transpose(source)
            oriented.load()

            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
            else:
                image = oriented.convert("RGB")

            original_width, original_height = image.size
            scale = min(
                1.0,
                settings.AI_WORKING_IMAGE_MAX_PX
                / max(original_width, original_height),
            )
            if scale < 1.0:
                width = max(1, round(original_width * scale))
                height = max(1, round(original_height * scale))
                image = image.resize(
                    (width, height),
                    resample=Image.Resampling.LANCZOS,
                )

            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=WORKING_JPEG_QUALITY,
                optimize=True,
                exif=b"",
            )
            return WorkingImage(
                bytes=output.getvalue(),
                mime_type="image/jpeg",
                width_px=image.width,
                height_px=image.height,
                scale_factor=scale,
            )
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise RuntimeError("The stored image could not be decoded for AI processing.") from exc


def validate_generated_image(image_bytes: bytes) -> tuple[str, int, int]:
    """Return image MIME type and dimensions, rejecting malformed or tiny output."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            mime_type = Image.MIME.get(image.format or "")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError("The generated image could not be decoded.") from exc

    if not mime_type or width < 256 or height < 256:
        raise ValueError("The generated image is too small or has an unsupported format.")
    return mime_type, width, height
