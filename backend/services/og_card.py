"""Dynamic Open Graph card image generator for shared team pages.

Produces a 1200x630 PNG (Twitter summary_large_image dimensions) featuring:
team name, season, club crest, and a row of player avatars.
"""
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from typing import Optional, List

# 1200x630 = standard Twitter / FB / WhatsApp large card size
W, H = 1200, 630

# Colors (match app aesthetic)
BG_TOP = (15, 26, 46)        # #0F1A2E
BG_BOTTOM = (10, 10, 10)     # #0A0A0A
ACCENT = (0, 122, 255)       # #007AFF
WHITE = (255, 255, 255)
SUBTLE = (163, 163, 163)     # #A3A3A3
CARD_BORDER = (255, 255, 255, 25)

# Liberation Sans is bundled in most Linux distros (Debian-based ones used here)
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _gradient_bg(img: Image.Image) -> None:
    """Vertical gradient from BG_TOP → BG_BOTTOM."""
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font_path: str, max_width: int,
              start_size: int, min_size: int = 32) -> ImageFont.FreeTypeFont:
    """Find the largest font size where text fits within max_width."""
    size = start_size
    while size >= min_size:
        font = _load_font(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 4
    return _load_font(font_path, min_size)


def _circle_crop(image_bytes: bytes, diameter: int) -> Optional[Image.Image]:
    """Resize to square and apply circular alpha mask."""
    try:
        src = Image.open(BytesIO(image_bytes)).convert("RGBA")
    except Exception:
        return None
    src = src.resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.ellipse((0, 0, diameter, diameter), fill=255)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


def _fit_image(image_bytes: bytes, box: int) -> Optional[Image.Image]:
    """Fit an image inside a square box preserving aspect ratio (transparent bg)."""
    try:
        src = Image.open(BytesIO(image_bytes)).convert("RGBA")
    except Exception:
        return None
    src.thumbnail((box, box), Image.LANCZOS)
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    canvas.paste(src, ((box - src.width) // 2, (box - src.height) // 2), src)
    return canvas


def render_team_card(
    team_name: str,
    season: str,
    club_name: str = "",
    player_count: int = 0,
    club_logo_bytes: Optional[bytes] = None,
    player_avatars: Optional[List[bytes]] = None,
) -> bytes:
    """Render the full OG card and return PNG bytes."""
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    # Subtle blue accent bar on far-left
    draw.rectangle([(0, 0), (8, H)], fill=ACCENT)

    # Top label "PUBLIC TEAM PAGE"
    label_font = _load_font(FONT_BOLD, 22)
    draw.text((64, 56), "PUBLIC TEAM PAGE", font=label_font, fill=ACCENT)

    # Right-side club crest
    crest_box = 260
    crest_x = W - crest_box - 64
    crest_y = (H - crest_box) // 2 - 30
    if club_logo_bytes:
        crest = _fit_image(club_logo_bytes, crest_box)
        if crest:
            # White-ish backing card so the crest pops on the dark gradient
            backing = Image.new("RGBA", (crest_box + 32, crest_box + 32), (255, 255, 255, 12))
            img.paste(backing, (crest_x - 16, crest_y - 16), backing)
            img.paste(crest, (crest_x, crest_y), crest)
    text_max_w = crest_x - 64 - 32 if club_logo_bytes else W - 128

    # Team name (huge)
    name_font = _fit_text(draw, team_name, FONT_BOLD, text_max_w, start_size=104, min_size=56)
    draw.text((64, 110), team_name, font=name_font, fill=WHITE)

    # Sub-line: Club • Season • N players
    sub_parts = []
    if club_name:
        sub_parts.append(club_name)
    sub_parts.append(season)
    sub_parts.append(f"{player_count} {'Player' if player_count == 1 else 'Players'}")
    sub_line = "  •  ".join(sub_parts)

    # Position sub-line just below the name
    name_bbox = draw.textbbox((64, 110), team_name, font=name_font)
    sub_y = name_bbox[3] + 18
    sub_font = _load_font(FONT_REG, 32)
    draw.text((64, sub_y), sub_line, font=sub_font, fill=SUBTLE)

    # Player avatar row (bottom)
    if player_avatars:
        avatar_size = 88
        gap = 16
        max_show = 6
        avatars = [a for a in player_avatars[:max_show] if a]
        n = len(avatars)
        start_x = 64
        avatar_y = H - avatar_size - 80
        for i, a_bytes in enumerate(avatars):
            crop = _circle_crop(a_bytes, avatar_size)
            if not crop:
                continue
            x = start_x + i * (avatar_size + gap)
            # Subtle ring
            ring = Image.new("RGBA", (avatar_size + 6, avatar_size + 6), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse(
                (0, 0, avatar_size + 5, avatar_size + 5),
                outline=ACCENT, width=3,
            )
            img.paste(ring, (x - 3, avatar_y - 3), ring)
            img.paste(crop, (x, avatar_y), crop)

        if player_count > n:
            extra_x = start_x + n * (avatar_size + gap)
            extra_font = _load_font(FONT_BOLD, 22)
            draw.ellipse(
                (extra_x, avatar_y, extra_x + avatar_size, avatar_y + avatar_size),
                fill=(31, 31, 31), outline=(60, 60, 60), width=2,
            )
            extra_text = f"+{player_count - n}"
            ebox = draw.textbbox((0, 0), extra_text, font=extra_font)
            ew = ebox[2] - ebox[0]
            eh = ebox[3] - ebox[1]
            draw.text(
                (extra_x + (avatar_size - ew) // 2, avatar_y + (avatar_size - eh) // 2 - 4),
                extra_text, font=extra_font, fill=WHITE,
            )

    # Bottom-right brand
    brand_font = _load_font(FONT_BOLD, 22)
    brand = "SOCCER SCOUT"
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    bw = bbox[2] - bbox[0]
    draw.text((W - bw - 64, H - 56), brand, font=brand_font, fill=WHITE)
    # Small dot before brand
    draw.ellipse(
        (W - bw - 84, H - 50, W - bw - 72, H - 38),
        fill=ACCENT,
    )

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
