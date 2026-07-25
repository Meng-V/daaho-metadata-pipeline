import io
import os
from pathlib import Path
from typing import Tuple
from PIL import Image, ImageOps
try:
    import pytesseract
except ImportError:
    pytesseract = None

# Formats the vision API accepts directly. For these we send the original file bytes untouched,
# provided they are within MAX_PIXELS.
PASSTHROUGH_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Pixel ceiling for images sent with detail="original".
#
# Measured on the 19-image pilot (out_v4/, tier terra): transcript self-confidence collapses on
# very large scans even though detail="original" is documented to preserve input dimensions.
#
#     ~15 MP  (3400x4400)  ->  confidence 85-99 on 13 of 13 items
#      31.5 MP (4914x6412) ->  confidence 91
#      35.3 MP (5222x6762) ->  confidence 57
#      35.6 MP (5250x6776) ->  confidence 65 and 25  (the 25 was a fabricated transcript)
#      39.5 MP (5356x7377) ->  confidence 72
#
# Past roughly 32 MP the model stops reading the page reliably and starts inventing plausible
# period documents -- see KNOWN_ISSUES.md. Downscaling into the proven range is both more accurate
# and cheaper, since image tokens scale with area. 2000px on the shortest side is still far above
# the 768px that tile-resizing models impose.
# 15 MP is the proven-safe default: every item in the ~15 MP group scored 85-99, and capping
# BC-0934 (35.6 MP) to 15 MP took it from a fabricated transcript to the real document. 24 MP was
# tested and still fabricated. Override with MAX_IMAGE_PIXELS_SENT if a future batch needs more.
MAX_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS_SENT", str(15_000_000)))
JPEG_QUALITY = 92


def _downscale_to_budget(im: Image.Image, max_pixels: int) -> Image.Image:
    scale = (max_pixels / (im.width * im.height)) ** 0.5
    new_size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
    return im.resize(new_size, Image.LANCZOS)


def image_bytes(img_path: str, max_pixels: int = 0) -> Tuple[bytes, str]:
    """Return (bytes, mime_type) for the vision API.

    Sends the original file untouched when the format is supported and the image is within the
    pixel budget. This function used to re-encode every image to full-resolution PNG, which
    inflated a 3 MB JPEG into a 25.8 MB PNG (34.4 MB once base64-encoded) while adding no detail.
    """
    max_pixels = max_pixels or MAX_PIXELS
    path = Path(img_path)
    suffix = path.suffix.lower()

    with Image.open(img_path) as probe:
        within_budget = probe.width * probe.height <= max_pixels

    if suffix in PASSTHROUGH_MIME and within_budget:
        return path.read_bytes(), PASSTHROUGH_MIME[suffix]

    with Image.open(img_path) as im:
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if im.width * im.height > max_pixels:
            im = _downscale_to_budget(im, max_pixels)
        buffer = io.BytesIO()
        im.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        return buffer.getvalue(), "image/jpeg"


def tesseract_available() -> bool:
    """Whether local OCR can actually run. False silently disables tesseract_ocr()."""
    return pytesseract is not None


def image_dimensions(img_path: str) -> Tuple[int, int]:
    try:
        with Image.open(img_path) as im:
            return im.size
    except Exception:
        return (0, 0)


def sent_dimensions(data: bytes) -> Tuple[int, int]:
    """Dimensions of the encoded bytes actually sent, which may be below the source after capping."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return (0, 0)


def tesseract_ocr(img_path: str) -> Tuple[str, float]:
    """Local OCR. Runs on this machine and costs nothing."""
    if pytesseract is None:
        return "", 0.0
    try:
        with Image.open(img_path) as im:
            gray = ImageOps.grayscale(im)
            text = pytesseract.image_to_string(gray)
            alnum = sum(c.isalnum() for c in text)
            conf = min(95.0, max(5.0, (alnum / max(1, len(text))) * 100.0)) if text else 0.0
            return text, conf
    except Exception:
        return "", 0.0
