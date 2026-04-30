"""Club crest image pipeline.

Coaches upload an arbitrary club crest (any size, JPEG/PNG/WEBP). The pipeline:
1. Detects whether the image already has alpha (transparent) or a uniform background
2. If solid background detected (corners are all near the same color), strips it
   to transparent so the crest blends into dark/light themes alike
3. Generates a square-padded transparent PNG so the crest renders consistently
   in OG cards (Pillow paste) and HTML <img> tags
4. Returns the processed bytes; the caller stores them via the existing storage backend
"""
from io import BytesIO
import logging
from typing import Optional
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# How aggressively to remove a background. Higher = more pixels turn transparent.
# 30 is conservative — only near-identical-to-corner pixels get masked out.
BG_TOLERANCE = 35
# Output crest target size — fits inside an OG card avatar slot at 1x and 2x.
CREST_SIZE = 512


def _detect_uniform_background(arr: np.ndarray) -> Optional[tuple]:
    """Return the corner background color if all 4 corners agree (within
    tolerance), otherwise None. Uses 4x4 corner samples to reduce noise.
    """
    h, w = arr.shape[:2]
    if h < 8 or w < 8:
        return None
    corners = [
        arr[0:4, 0:4],
        arr[0:4, w - 4:w],
        arr[h - 4:h, 0:4],
        arr[h - 4:h, w - 4:w],
    ]
    means = [np.array(c[..., :3].reshape(-1, 3).mean(axis=0)) for c in corners]
    base = means[0]
    for m in means[1:]:
        if np.linalg.norm(m - base) > 30:
            return None
    return tuple(int(x) for x in base)


def _remove_background(img: Image.Image) -> Image.Image:
    """Convert pixels matching the detected uniform background to transparent.
    No-op if the image already has alpha channel with non-trivial content,
    OR if no uniform background is detected.
    """
    img = img.convert("RGBA")
    arr = np.array(img)

    # If image already has meaningful alpha (>1% pixels are <255), skip.
    if (arr[..., 3] < 250).sum() > 0.01 * arr.shape[0] * arr.shape[1]:
        return img

    bg = _detect_uniform_background(arr)
    if bg is None:
        return img

    r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), arr[..., 2].astype(int)
    diff = np.sqrt(
        (r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2
    )
    arr[..., 3] = np.where(diff < BG_TOLERANCE, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def process_crest(image_bytes: bytes) -> bytes:
    """Take raw upload bytes; return a transparent-bg square PNG ready to store.

    Output is always exactly CREST_SIZE x CREST_SIZE PNG with alpha so it
    composites cleanly anywhere in the app.
    """
    try:
        src = Image.open(BytesIO(image_bytes))
    except Exception as e:
        raise ValueError(f"Could not decode image: {e}") from e

    # Force RGBA so the rest of the pipeline doesn't have to special-case modes.
    src = src.convert("RGBA")
    src = _remove_background(src)

    # Crop tight around non-transparent pixels so resizing preserves detail.
    bbox = src.getbbox()
    if bbox:
        src = src.crop(bbox)

    # Letterbox into a transparent square canvas
    side = max(src.width, src.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(src, ((side - src.width) // 2, (side - src.height) // 2), src)

    # Final downsample to CREST_SIZE
    canvas.thumbnail((CREST_SIZE, CREST_SIZE), Image.LANCZOS)
    out = BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()
