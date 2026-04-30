"""Dynamic Open Graph card image generator for shared team pages.

Produces a 1200x630 PNG (Twitter summary_large_image dimensions) featuring:
team name, season, club crest, and a row of player avatars.
"""
import os
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


# ===== Brand lockup =====
# Path to the transparent-background logo mark (PNG with alpha channel).
# We try a few likely deployment locations so the OG generator works in
# both dev and prod containers.
_LOGO_LOCKUP_CACHE: Optional[Image.Image] = None
_LOGO_CANDIDATES = [
    "/app/frontend/public/logo-mark.png",
    "/app/frontend/build/logo-mark.png",
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public", "logo-mark.png"),
]


def _load_logo_lockup() -> Optional[Image.Image]:
    global _LOGO_LOCKUP_CACHE
    if _LOGO_LOCKUP_CACHE is not None:
        return _LOGO_LOCKUP_CACHE
    for path in _LOGO_CANDIDATES:
        try:
            if os.path.exists(path):
                _LOGO_LOCKUP_CACHE = Image.open(path).convert("RGBA")
                return _LOGO_LOCKUP_CACHE
        except Exception:
            continue
    return None


def _paste_brand_lockup(img: Image.Image, position: str = "right") -> None:
    """Draw the Soccer Scout 11 logo lockup at the bottom of the OG card.

    `position` is "right" (default) or "left" — clip cards put the logo on the
    left because the right is occupied by a big play icon.

    Falls back to the previous text-only treatment if the logo file is missing
    so OG cards still render in environments where the asset wasn't bundled.
    """
    target_h = 56
    margin_x, margin_y = 64, 36
    logo = _load_logo_lockup()
    if logo is not None:
        ratio = target_h / logo.height
        scaled = logo.resize((int(logo.width * ratio), target_h), Image.LANCZOS)
        if position == "left":
            x = margin_x
        else:
            x = W - scaled.width - margin_x
        y = H - scaled.height - margin_y
        img.paste(scaled, (x, y), scaled)
        return
    # Fallback: text brand
    draw = ImageDraw.Draw(img)
    brand_font = _load_font(FONT_BOLD, 22)
    brand = "SOCCER SCOUT 11"
    bbox = draw.textbbox((0, 0), brand, font=brand_font)
    bw = bbox[2] - bbox[0]
    if position == "left":
        draw.text((64, H - 56), brand, font=brand_font, fill=WHITE)
        draw.ellipse((44, H - 50, 56, H - 38), fill=ACCENT)
    else:
        draw.text((W - bw - 64, H - 56), brand, font=brand_font, fill=WHITE)
        draw.ellipse((W - bw - 84, H - 50, W - bw - 72, H - 38), fill=ACCENT)


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

    # Bottom-right brand lockup (Soccer Scout 11 logo)
    _paste_brand_lockup(img)

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_folder_card(
    folder_name: str,
    coach_name: str = "",
    match_count: int = 0,
    recent_matches: Optional[List[str]] = None,
    label: str = "MATCH FILM FOLDER",
) -> bytes:
    """Render OG card for a shared match-film folder (or clip-collection)."""
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (8, H)], fill=ACCENT)

    label_font = _load_font(FONT_BOLD, 22)
    draw.text((64, 56), label, font=label_font, fill=ACCENT)

    name_font = _fit_text(draw, folder_name, FONT_BOLD, W - 200, start_size=104, min_size=52)
    draw.text((64, 110), folder_name, font=name_font, fill=WHITE)

    name_bbox = draw.textbbox((64, 110), folder_name, font=name_font)
    sub_y = name_bbox[3] + 22

    sub_parts = [f"{match_count} {'Match' if match_count == 1 else 'Matches'}"]
    if coach_name:
        sub_parts.append(f"Coach {coach_name}")
    sub_line = "  •  ".join(sub_parts)

    sub_font = _load_font(FONT_REG, 32)
    draw.text((64, sub_y), sub_line, font=sub_font, fill=SUBTLE)

    # Recent match preview cards (rectangles)
    if recent_matches:
        card_y = H - 200
        card_h = 100
        gap = 16
        max_show = 3
        items = recent_matches[:max_show]
        n = len(items)
        # Compute width to fill remaining space evenly
        total_w = W - 128
        card_w = (total_w - gap * (n - 1)) // n if n > 0 else total_w
        for i, label in enumerate(items):
            x = 64 + i * (card_w + gap)
            draw.rectangle((x, card_y, x + card_w, card_y + card_h),
                           fill=(20, 20, 20), outline=(60, 60, 60), width=1)
            draw.rectangle((x, card_y, x + 4, card_y + card_h), fill=ACCENT)
            label_font2 = _load_font(FONT_BOLD, 22)
            # Truncate label if too long
            shown = label
            while draw.textbbox((0, 0), shown, font=label_font2)[2] > card_w - 32 and len(shown) > 4:
                shown = shown[:-2]
            if shown != label:
                shown = shown[:-1] + "…"
            draw.text((x + 20, card_y + 38), shown, font=label_font2, fill=WHITE)

    # Brand lockup
    _paste_brand_lockup(img)

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_clip_card(
    clip_title: str,
    match_label: str = "",
    coach_name: str = "",
    duration_sec: float = 0.0,
    clip_type: str = "highlight",
) -> bytes:
    """Render OG card for an individual shared clip."""
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (8, H)], fill=ACCENT)

    # Type-coded label colour
    type_color = {
        "goal": (74, 222, 128),       # green
        "save": (96, 165, 250),       # blue
        "foul": (239, 68, 68),        # red
        "card": (251, 191, 36),       # amber
        "highlight": ACCENT,
    }.get(clip_type.lower(), ACCENT)

    label_font = _load_font(FONT_BOLD, 22)
    type_label = clip_type.upper()
    draw.text((64, 56), f"VIDEO CLIP  •  {type_label}", font=label_font, fill=type_color)

    # Big play icon (triangle) on right — visual cue this is video
    tri_size = 200
    tri_cx = W - 160
    tri_cy = H // 2 - 30
    triangle = [
        (tri_cx - tri_size // 2, tri_cy - tri_size // 2),
        (tri_cx - tri_size // 2, tri_cy + tri_size // 2),
        (tri_cx + tri_size // 2, tri_cy),
    ]
    # Outer ring
    ring_r = tri_size + 30
    draw.ellipse(
        (tri_cx - ring_r // 2, tri_cy - ring_r // 2,
         tri_cx + ring_r // 2, tri_cy + ring_r // 2),
        outline=type_color, width=4,
    )
    draw.polygon(triangle, fill=type_color)

    text_max_w = W - tri_cx - tri_size // 2 - 64 - 64
    if text_max_w < 600:
        text_max_w = 600
    text_max_w = tri_cx - 64 - tri_size // 2 - 32

    name_font = _fit_text(draw, clip_title, FONT_BOLD, text_max_w, start_size=88, min_size=40)
    draw.text((64, 120), clip_title, font=name_font, fill=WHITE)

    name_bbox = draw.textbbox((64, 120), clip_title, font=name_font)
    sub_y = name_bbox[3] + 18

    sub_parts = []
    if match_label:
        sub_parts.append(match_label)
    if duration_sec > 0:
        mins = int(duration_sec // 60)
        secs = int(duration_sec % 60)
        sub_parts.append(f"{mins}:{secs:02d}")
    if coach_name:
        sub_parts.append(f"Coach {coach_name}")
    if sub_parts:
        sub_font = _load_font(FONT_REG, 30)
        draw.text((64, sub_y), "  •  ".join(sub_parts), font=sub_font, fill=SUBTLE)

    # Brand lockup (bottom-left to leave room for the play triangle on right)
    _paste_brand_lockup(img, position="left")

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()



def render_player_card(
    name: str,
    number: Optional[int] = None,
    position: str = "",
    teams_summary: str = "",
    stats: Optional[dict] = None,
    coach_name: str = "",
    profile_pic_bytes: Optional[bytes] = None,
) -> bytes:
    """Render OG card for a public player dossier."""
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (8, H)], fill=ACCENT)

    label_font = _load_font(FONT_BOLD, 22)
    draw.text((64, 56), "PLAYER PROFILE", font=label_font, fill=ACCENT)

    # Avatar circle on the right
    avatar_size = 280
    avatar_x = W - avatar_size - 64
    avatar_y = (H - avatar_size) // 2 - 10
    if profile_pic_bytes:
        crop = _circle_crop(profile_pic_bytes, avatar_size)
        if crop:
            ring_size = avatar_size + 16
            ring = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse(
                (0, 0, ring_size - 1, ring_size - 1),
                outline=ACCENT, width=4,
            )
            img.paste(ring, (avatar_x - 8, avatar_y - 8), ring)
            img.paste(crop, (avatar_x, avatar_y), crop)
    else:
        # Placeholder ring
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill=(31, 31, 31), outline=ACCENT, width=4,
        )
        ph_font = _load_font(FONT_BOLD, 96)
        ph = (name or "?")[0].upper()
        bbox = draw.textbbox((0, 0), ph, font=ph_font)
        draw.text(
            (avatar_x + (avatar_size - (bbox[2] - bbox[0])) // 2,
             avatar_y + (avatar_size - (bbox[3] - bbox[1])) // 2 - 16),
            ph, font=ph_font, fill=WHITE,
        )

    text_max_w = avatar_x - 64 - 32

    # Jersey number (huge, blue) + name
    if number is not None:
        num_font = _load_font(FONT_BOLD, 144)
        num_str = f"#{number}"
        draw.text((64, 100), num_str, font=num_font, fill=ACCENT)
        num_bbox = draw.textbbox((64, 100), num_str, font=num_font)
        name_x = num_bbox[2] + 24
        avail = text_max_w - (name_x - 64)
        name_font = _fit_text(draw, name, FONT_BOLD, avail, start_size=88, min_size=44)
        # Vertically align name baseline with bottom of number
        nb = draw.textbbox((0, 0), name, font=name_font)
        name_h = nb[3] - nb[1]
        name_y = num_bbox[3] - name_h - 30
        draw.text((name_x, name_y), name, font=name_font, fill=WHITE)
        sub_y = num_bbox[3] + 12
    else:
        name_font = _fit_text(draw, name, FONT_BOLD, text_max_w, start_size=104, min_size=52)
        draw.text((64, 110), name, font=name_font, fill=WHITE)
        sub_y = draw.textbbox((64, 110), name, font=name_font)[3] + 18

    # Position + teams summary
    sub_parts = []
    if position:
        sub_parts.append(position)
    if teams_summary:
        sub_parts.append(teams_summary)
    if sub_parts:
        sub_font = _load_font(FONT_REG, 30)
        draw.text((64, sub_y), "  •  ".join(sub_parts), font=sub_font, fill=SUBTLE)
        sub_y += 50

    # Stats chips (Goals, Saves, Highlights, etc.)
    if stats:
        chip_y = max(sub_y + 20, H - 200)
        chip_x = 64
        chip_font = _load_font(FONT_BOLD, 26)
        small_font = _load_font(FONT_REG, 16)
        # Show top 4 non-zero buckets
        priority = ["goal", "save", "foul", "card", "highlight", "shot", "chance"]
        ordered = [k for k in priority if (stats.get(k) or 0) > 0]
        for k in ordered[:4]:
            label = k.upper() + ("S" if not k.endswith("s") else "")
            count = str(stats[k])
            # Chip: count over label
            count_bbox = draw.textbbox((0, 0), count, font=chip_font)
            label_bbox = draw.textbbox((0, 0), label, font=small_font)
            chip_w = max(count_bbox[2] - count_bbox[0], label_bbox[2] - label_bbox[0]) + 32
            draw.rectangle(
                (chip_x, chip_y, chip_x + chip_w, chip_y + 90),
                fill=(20, 20, 20), outline=(60, 60, 60), width=1,
            )
            draw.rectangle((chip_x, chip_y, chip_x + 4, chip_y + 90), fill=ACCENT)
            cw = count_bbox[2] - count_bbox[0]
            draw.text((chip_x + (chip_w - cw) // 2, chip_y + 12),
                      count, font=chip_font, fill=WHITE)
            lw = label_bbox[2] - label_bbox[0]
            draw.text((chip_x + (chip_w - lw) // 2, chip_y + 60),
                      label, font=small_font, fill=SUBTLE)
            chip_x += chip_w + 12

    # Coach + brand
    if coach_name:
        coach_font = _load_font(FONT_REG, 18)
        draw.text((64, H - 90), f"Shared by Coach {coach_name}",
                  font=coach_font, fill=(120, 120, 120))

    _paste_brand_lockup(img)

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()



def render_match_recap_card(
    team_home: str,
    team_away: str,
    home_score: int,
    away_score: int,
    competition: str = "",
    coach_name: str = "",
    recap_text: str = "",
    outcome: str = "D",
) -> bytes:
    """Render OG card for a finished match recap.

    Layout: left strip accent + label "MATCH RECAP", big team-vs-team title,
    centered scoreline (Bebas-style), one-line meta, and a clamped recap excerpt.
    """
    img = Image.new("RGB", (W, H), BG_BOTTOM)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    # Left accent strip — green for win, red for loss, amber for draw (from home's perspective)
    accent = (16, 185, 129) if outcome == "W" else (239, 68, 68) if outcome == "L" else (251, 191, 36)
    draw.rectangle([(0, 0), (8, H)], fill=accent)

    # Label
    label_font = _load_font(FONT_BOLD, 22)
    draw.text((64, 56), "MATCH RECAP", font=label_font, fill=accent)

    # Team-vs-team title
    matchup = f"{team_home} vs {team_away}"
    title_font = _fit_text(draw, matchup, FONT_BOLD, W - 200, start_size=72, min_size=36)
    draw.text((64, 102), matchup, font=title_font, fill=WHITE)
    title_bbox = draw.textbbox((64, 102), matchup, font=title_font)
    title_bottom = title_bbox[3]

    # Score row — big and proud
    score_font = _load_font(FONT_BOLD, 96)
    score_text = f"{home_score} – {away_score}"
    score_bbox = draw.textbbox((0, 0), score_text, font=score_font)
    score_w = score_bbox[2] - score_bbox[0]
    score_x = 64
    score_y = title_bottom + 24
    draw.text((score_x, score_y), score_text, font=score_font, fill=WHITE)

    # Outcome chip beside the score
    outcome_label = {"W": "WIN", "L": "LOSS", "D": "DRAW"}.get(outcome, "—")
    chip_font = _load_font(FONT_BOLD, 24)
    chip_bbox = draw.textbbox((0, 0), outcome_label, font=chip_font)
    chip_w = chip_bbox[2] - chip_bbox[0] + 32
    chip_h = 44
    chip_x = score_x + score_w + 32
    chip_y = score_y + 36
    draw.rectangle(
        (chip_x, chip_y, chip_x + chip_w, chip_y + chip_h),
        fill=accent,
    )
    draw.text((chip_x + 16, chip_y + 8), outcome_label, font=chip_font, fill=(0, 0, 0))

    # Meta line (competition · coach)
    meta_parts = []
    if competition:
        meta_parts.append(competition)
    if coach_name:
        meta_parts.append(f"Coach {coach_name}")
    meta_y = score_y + 110
    if meta_parts:
        meta_font = _load_font(FONT_REG, 26)
        draw.text((64, meta_y), "  •  ".join(meta_parts), font=meta_font, fill=SUBTLE)
        meta_y += 40

    # Recap excerpt — wrap to 2-3 lines, ending with ellipsis if truncated
    if recap_text:
        recap_font = _load_font(FONT_REG, 24)
        max_w = W - 128
        words = recap_text.split()
        lines = []
        current = ""
        for w in words:
            test = (current + " " + w).strip()
            if draw.textbbox((0, 0), test, font=recap_font)[2] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
            if len(lines) >= 3:
                break
        if current and len(lines) < 3:
            lines.append(current)
        # If we ran out of words mid-flight, append ellipsis to last line
        if len(lines) >= 3 and current and current != lines[-1]:
            lines[-1] = lines[-1].rstrip(".,;: ") + "…"
        for i, line in enumerate(lines[:3]):
            draw.text((64, meta_y + i * 32), line, font=recap_font, fill=(220, 220, 220))

    # Brand lockup (bottom-right)
    _paste_brand_lockup(img)

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
