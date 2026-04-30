"""Branded scouting packet PDF generator.

Admin-gated endpoint produces a 4-page PDF a coach can email/print for
college recruiters:
  Page 1 — Cover (logo + club crest + player headline)
  Page 2 — Season stats + strengths/weaknesses from AI
  Page 3 — Performance chart (per-match goal contribution)
  Page 4 — Clips index (each clip as a row with QR code to the shareable URL)
  [Page 5 — optional coach notes / recommendation, appended when supplied]

Pure ReportLab — no OS deps beyond what's in the standard Python image.
"""
import logging
import os
from io import BytesIO
from typing import Optional

import qrcode
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT

logger = logging.getLogger(__name__)

# Brand palette (matches the app)
INK = colors.HexColor("#0A0A0A")
PAPER = colors.white
ACCENT = colors.HexColor("#007AFF")
MUTED = colors.HexColor("#666666")
SUBTLE = colors.HexColor("#A3A3A3")
SURFACE = colors.HexColor("#F2F2F2")
GREEN = colors.HexColor("#10B981")
RED = colors.HexColor("#EF4444")
AMBER = colors.HexColor("#FBBF24")

PAGE_W, PAGE_H = letter  # 612 x 792 pt
MARGIN = 0.6 * inch

_LOGO_CANDIDATES = [
    "/app/frontend/public/logo-mark.png",
    "/app/frontend/build/logo-mark.png",
]


def _find_logo() -> Optional[str]:
    for p in _LOGO_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _draw_footer(c: canvas.Canvas, page_num: int, total_pages: int, player_label: str) -> None:
    """Bottom-of-page footer: logo on left, page counter + player name on right."""
    c.setFillColor(SUBTLE)
    c.setFont("Helvetica", 8)
    logo = _find_logo()
    footer_y = MARGIN - 0.15 * inch
    if logo:
        try:
            c.drawImage(
                logo, MARGIN, footer_y - 4, width=0.55 * inch, height=0.22 * inch,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass
    c.drawRightString(
        PAGE_W - MARGIN, footer_y,
        f"{player_label}  •  Page {page_num} of {total_pages}",
    )


def _paragraph(text: str, font_size: int = 10, color: colors.Color = INK) -> Paragraph:
    style = ParagraphStyle(
        name="body",
        fontName="Helvetica",
        fontSize=font_size,
        leading=font_size * 1.4,
        textColor=color,
        alignment=TA_LEFT,
    )
    return Paragraph(text, style)


def _draw_page_header(c: canvas.Canvas, label: str, sub: str = "") -> float:
    """Top-of-page eyebrow label + thin accent bar. Returns the y where body content can start."""
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN, PAGE_H - MARGIN, label.upper())
    c.setFillColor(INK)
    c.setLineWidth(0.8)
    c.setStrokeColor(ACCENT)
    c.line(MARGIN, PAGE_H - MARGIN - 4, MARGIN + 0.5 * inch, PAGE_H - MARGIN - 4)
    if sub:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 9)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN, sub)
    return PAGE_H - MARGIN - 0.4 * inch  # y for body start


# ---------- Page 1: Cover ----------

def _draw_cover(c: canvas.Canvas, packet: dict) -> None:
    player = packet["player"]
    club = packet.get("club") or {}
    season = packet.get("season", "")
    coach_name = packet.get("coach_name", "")

    # Dark hero background
    c.setFillColor(INK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Accent bar top
    c.setFillColor(ACCENT)
    c.rect(0, PAGE_H - 0.18 * inch, PAGE_W, 0.18 * inch, fill=1, stroke=0)

    # Logo top-right
    logo = _find_logo()
    if logo:
        try:
            c.drawImage(
                logo, PAGE_W - MARGIN - 1.6 * inch, PAGE_H - 1.0 * inch,
                width=1.6 * inch, height=0.6 * inch,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass

    c.setFillColor(colors.HexColor("#A3A3A3"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, PAGE_H - 0.7 * inch, "SCOUTING PACKET")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN, PAGE_H - 0.7 * inch - 14, season.upper() if season else "PLAYER PROFILE")

    # Player big name block
    name = (player.get("name") or "Unknown Player").upper()
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 48)
    c.drawString(MARGIN, PAGE_H - 2.8 * inch, name[:24])
    if len(name) > 24:
        c.setFont("Helvetica-Bold", 30)
        c.drawString(MARGIN, PAGE_H - 3.2 * inch, name[24:48])

    # Jersey number + position
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 72)
    if player.get("number") is not None:
        c.drawString(MARGIN, PAGE_H - 4.2 * inch, f"#{player['number']}")
    c.setFillColor(SUBTLE)
    c.setFont("Helvetica", 14)
    pos = (player.get("position") or "").upper()
    if pos:
        c.drawString(MARGIN + 1.5 * inch, PAGE_H - 4.0 * inch, pos)

    # Club + crest row
    crest_bytes = packet.get("club_crest_bytes")
    if crest_bytes:
        try:
            img = Image.open(BytesIO(crest_bytes)).convert("RGBA")
            c.drawInlineImage(
                img, MARGIN, PAGE_H - 5.6 * inch,
                width=1.0 * inch, height=1.0 * inch,
                preserveAspectRatio=True,
            )
        except Exception:
            pass
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 14)
    club_name = club.get("name") or player.get("club_name") or ""
    c.drawString(MARGIN + 1.2 * inch, PAGE_H - 5.1 * inch, club_name)
    c.setFillColor(SUBTLE)
    c.setFont("Helvetica", 10)
    teams_summary = packet.get("teams_summary") or ""
    if teams_summary:
        c.drawString(MARGIN + 1.2 * inch, PAGE_H - 5.1 * inch - 16, teams_summary[:80])

    # Prepared by footer (on cover)
    c.setFillColor(SUBTLE)
    c.setFont("Helvetica", 9)
    if coach_name:
        c.drawString(MARGIN, 1.0 * inch, f"Prepared by Coach {coach_name}")
    c.drawString(MARGIN, 1.0 * inch - 14, f"Generated {packet.get('generated_at_label', '')}")
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(PAGE_W - MARGIN, 1.0 * inch, "SOCCERSCOUT11.COM")


# ---------- Page 2: Stats ----------

def _draw_stat_tile(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, value: str, color: colors.Color = INK) -> None:
    c.setFillColor(SURFACE)
    c.rect(x, y, w, h, fill=1, stroke=0)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + 10, y + h - 14, label.upper())
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(x + 10, y + 12, value)


def _draw_stats_page(c: canvas.Canvas, packet: dict) -> None:
    y = _draw_page_header(c, "Season Summary", packet.get("season", ""))
    stats = packet.get("stats", {})

    # 4 stat tiles across the top
    tile_w = (PAGE_W - 2 * MARGIN - 0.3 * inch) / 4
    tile_h = 0.95 * inch
    row_y = y - tile_h - 0.1 * inch
    tiles = [
        ("Matches", str(stats.get("matches", 0)), INK),
        ("Goals", str(stats.get("goals", 0)), GREEN),
        ("Assists", str(stats.get("assists", 0)), ACCENT),
        ("Minutes", str(stats.get("minutes", 0)), INK),
    ]
    for i, (label, val, clr) in enumerate(tiles):
        x = MARGIN + i * (tile_w + 0.1 * inch)
        _draw_stat_tile(c, x, row_y, tile_w, tile_h, label, val, clr)

    # Strengths section
    strengths = packet.get("strengths", []) or []
    weaknesses = packet.get("weaknesses", []) or []
    col_w = (PAGE_W - 2 * MARGIN - 0.3 * inch) / 2
    list_y_top = row_y - 0.35 * inch

    c.setFillColor(GREEN)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, list_y_top, "STRENGTHS")
    c.setStrokeColor(GREEN)
    c.setLineWidth(0.5)
    c.line(MARGIN, list_y_top - 3, MARGIN + col_w, list_y_top - 3)

    c.setFillColor(RED)
    c.drawString(MARGIN + col_w + 0.3 * inch, list_y_top, "FOCUS AREAS")
    c.setStrokeColor(RED)
    c.line(MARGIN + col_w + 0.3 * inch, list_y_top - 3, MARGIN + col_w + 0.3 * inch + col_w, list_y_top - 3)

    def _draw_bullet_list(x_anchor: float, items: list[str], color: colors.Color, list_y_start: float) -> None:
        c.setFillColor(INK)
        c.setFont("Helvetica", 10)
        cursor_y = list_y_start
        for item in items[:6]:
            # Draw bullet marker
            c.setFillColor(color)
            c.circle(x_anchor + 5, cursor_y + 3, 2, fill=1, stroke=0)
            # Draw wrapped text
            c.setFillColor(INK)
            style = ParagraphStyle(
                "bullet", fontName="Helvetica", fontSize=10, leading=13,
                textColor=INK, alignment=TA_LEFT,
            )
            p = Paragraph(item[:180], style)
            avail_w = col_w - 15
            _, h = p.wrap(avail_w, 60)
            p.drawOn(c, x_anchor + 14, cursor_y - h + 10)
            cursor_y -= max(h + 3, 18)

    _draw_bullet_list(MARGIN, strengths, GREEN, list_y_top - 0.25 * inch)
    _draw_bullet_list(MARGIN + col_w + 0.3 * inch, weaknesses, RED, list_y_top - 0.25 * inch)

    # Scout verdict callout (if present)
    verdict = packet.get("verdict")
    if verdict:
        y_v = 1.8 * inch
        c.setFillColor(INK)
        c.rect(MARGIN, y_v, PAGE_W - 2 * MARGIN, 1.1 * inch, fill=1, stroke=0)
        c.setFillColor(AMBER)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN + 14, y_v + 1.1 * inch - 18, "SCOUT VERDICT")
        c.setFillColor(PAPER)
        style = ParagraphStyle("verdict", fontName="Helvetica", fontSize=11, leading=15, textColor=PAPER)
        p = Paragraph(verdict[:500], style)
        p.wrapOn(c, PAGE_W - 2 * MARGIN - 28, 0.85 * inch)
        p.drawOn(c, MARGIN + 14, y_v + 14)


# ---------- Page 3: Chart ----------

def _draw_chart_page(c: canvas.Canvas, packet: dict) -> None:
    y = _draw_page_header(c, "Performance Trend", "Per-match goal contribution")
    per_match = packet.get("per_match", []) or []

    if not per_match:
        c.setFillColor(SUBTLE)
        c.setFont("Helvetica", 11)
        c.drawString(MARGIN, y - 1 * inch, "No per-match performance data available yet.")
        return

    # Bar chart — one bar per match, coloured by W/D/L
    chart_x = MARGIN
    chart_y = 2.5 * inch
    chart_w = PAGE_W - 2 * MARGIN
    chart_h = 3.5 * inch

    max_val = max(
        max((m.get("goals", 0) + m.get("assists", 0)) for m in per_match),
        1,
    )

    bars = per_match[-12:]  # last 12 matches
    bar_gap = 10
    bar_w = (chart_w - bar_gap * (len(bars) + 1)) / max(len(bars), 1)

    # Y-axis grid
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.setLineWidth(0.5)
    for i in range(5):
        gy = chart_y + (chart_h * i / 4)
        c.line(chart_x, gy, chart_x + chart_w, gy)
        c.setFillColor(SUBTLE)
        c.setFont("Helvetica", 7)
        c.drawRightString(chart_x - 4, gy - 2, f"{int(max_val * i / 4)}")

    for i, m in enumerate(bars):
        x = chart_x + bar_gap + i * (bar_w + bar_gap)
        val = m.get("goals", 0) + m.get("assists", 0)
        h = (val / max_val) * chart_h if max_val else 0
        result = (m.get("result") or "D").upper()
        fill = GREEN if result == "W" else (RED if result == "L" else AMBER)
        c.setFillColor(fill)
        c.rect(x, chart_y, bar_w, h, fill=1, stroke=0)
        # Value on top
        if val > 0:
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(x + bar_w / 2, chart_y + h + 3, str(val))
        # X-axis opponent label
        c.setFillColor(SUBTLE)
        c.setFont("Helvetica", 7)
        opponent = (m.get("opponent") or "").upper()[:8]
        c.drawCentredString(x + bar_w / 2, chart_y - 12, opponent)

    # Legend
    legend_y = chart_y - 0.7 * inch
    items = [("Win", GREEN), ("Draw", AMBER), ("Loss", RED)]
    lx = MARGIN
    for label, clr in items:
        c.setFillColor(clr)
        c.rect(lx, legend_y, 10, 10, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica", 9)
        c.drawString(lx + 16, legend_y + 2, label)
        lx += 1.1 * inch


# ---------- Page 4: Clips index ----------

def _qr_png(url: str) -> Image.Image:
    qr = qrcode.QRCode(version=1, box_size=8, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _draw_clips_page(c: canvas.Canvas, packet: dict) -> None:
    y = _draw_page_header(c, "Clips Index", f"{len(packet.get('clips') or [])} highlight{'s' if len(packet.get('clips') or []) != 1 else ''}")
    clips = packet.get("clips", []) or []
    base_url = packet.get("public_base_url", "")

    if not clips:
        c.setFillColor(SUBTLE)
        c.setFont("Helvetica", 11)
        c.drawString(MARGIN, y - 1 * inch, "No clips tagged to this player yet.")
        return

    row_h = 0.9 * inch
    cursor_y = y - row_h - 0.1 * inch
    for clip in clips[:8]:  # first page holds 8
        if cursor_y < 1.2 * inch:
            break
        # Row background alternating
        c.setFillColor(SURFACE)
        c.rect(MARGIN, cursor_y, PAGE_W - 2 * MARGIN, row_h - 8, fill=1, stroke=0)

        # QR code (shareable clip URL)
        share_token = clip.get("share_token")
        if share_token and base_url:
            url = f"{base_url}/clips/c/{share_token}"
            try:
                qr_img = _qr_png(url)
                c.drawInlineImage(
                    qr_img,
                    MARGIN + 8, cursor_y + 4,
                    width=row_h - 16, height=row_h - 16,
                )
            except Exception:
                pass
        else:
            # Placeholder block
            c.setFillColor(colors.HexColor("#E5E5E5"))
            c.rect(MARGIN + 8, cursor_y + 4, row_h - 16, row_h - 16, fill=1, stroke=0)

        # Title + meta
        text_x = MARGIN + row_h + 8
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 11)
        title = (clip.get("title") or "Untitled")[:80]
        c.drawString(text_x, cursor_y + row_h - 24, title)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 9)
        match_label = clip.get("match_label") or ""
        duration = clip.get("duration_label") or ""
        clip_type = (clip.get("clip_type") or "").upper()
        meta_parts = [p for p in (match_label, duration, clip_type) if p]
        c.drawString(text_x, cursor_y + row_h - 40, "  •  ".join(meta_parts))

        # Type chip on right
        if clip_type:
            chip_color = {
                "GOAL": GREEN,
                "FOUL": RED,
                "SAVE": ACCENT,
                "CARD": AMBER,
            }.get(clip_type, colors.HexColor("#A855F7"))
            c.setFillColor(chip_color)
            chip_w = 0.7 * inch
            c.rect(PAGE_W - MARGIN - chip_w - 10, cursor_y + row_h - 26, chip_w, 16, fill=1, stroke=0)
            c.setFillColor(PAPER)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(PAGE_W - MARGIN - chip_w / 2 - 10, cursor_y + row_h - 20, clip_type)

        cursor_y -= row_h

    c.setFillColor(SUBTLE)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, 1.2 * inch, "Scan any QR code with a phone camera to watch the clip.")
    if len(clips) > 8:
        c.drawRightString(
            PAGE_W - MARGIN, 1.2 * inch,
            f"+{len(clips) - 8} more clips at the shareable player profile.",
        )


# ---------- Page 5 (optional): Coach notes ----------

def _draw_notes_page(c: canvas.Canvas, packet: dict) -> None:
    y = _draw_page_header(c, "Coach's Recommendation", packet.get("coach_name", ""))
    notes = packet.get("coach_notes", "")

    style = ParagraphStyle(
        "notes",
        fontName="Helvetica",
        fontSize=12,
        leading=17,
        textColor=INK,
    )
    # Split the notes into paragraphs by blank lines so long recommendations wrap cleanly
    chunks = [chunk.strip() for chunk in notes.split("\n\n") if chunk.strip()]
    cursor_y = y - 0.3 * inch
    for chunk in chunks:
        p = Paragraph(chunk.replace("\n", "<br/>"), style)
        avail_w = PAGE_W - 2 * MARGIN
        _, h = p.wrap(avail_w, PAGE_H)
        if cursor_y - h < 1.3 * inch:
            break  # don't overflow onto another page
        p.drawOn(c, MARGIN, cursor_y - h)
        cursor_y -= h + 0.18 * inch


# ---------- Public API ----------

def render_scouting_packet(packet: dict) -> bytes:
    """Build the 4-or-5 page PDF. `packet` contract:
        player: {id, name, number, position, team_id?}
        club:   {id, name}
        season: str
        coach_name: str
        generated_at_label: str
        teams_summary: str ("Arsenal U21, Arsenal U18")
        club_crest_bytes: Optional[bytes]
        stats: {matches, goals, assists, minutes}
        strengths: [str]
        weaknesses: [str]
        verdict: Optional[str]   — short 2-sentence scout verdict
        per_match: [{opponent, goals, assists, result}]
        clips: [{title, share_token, match_label, duration_label, clip_type}]
        coach_notes: Optional[str]
        public_base_url: str
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    player_label = (packet.get("player") or {}).get("name", "Player")

    has_notes = bool((packet.get("coach_notes") or "").strip())
    total_pages = 5 if has_notes else 4

    # Page 1 — cover
    _draw_cover(c, packet)
    # no footer on cover (clean hero)
    c.showPage()

    # Page 2 — stats
    _draw_stats_page(c, packet)
    _draw_footer(c, 2, total_pages, player_label)
    c.showPage()

    # Page 3 — chart
    _draw_chart_page(c, packet)
    _draw_footer(c, 3, total_pages, player_label)
    c.showPage()

    # Page 4 — clips index
    _draw_clips_page(c, packet)
    _draw_footer(c, 4, total_pages, player_label)
    c.showPage()

    # Page 5 — optional notes
    if has_notes:
        _draw_notes_page(c, packet)
        _draw_footer(c, 5, total_pages, player_label)
        c.showPage()

    c.save()
    return buf.getvalue()
