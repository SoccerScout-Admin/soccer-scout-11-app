"""Coach Pulse weekly email — HTML template builder.

Uses inline CSS + table layout (email-client compatible). Pure-string output,
no Jinja since we want zero new deps.
"""
from __future__ import annotations
from typing import Optional
from html import escape


def _escape(s: Optional[str]) -> str:
    return escape(s or "", quote=True)


def _safe_text(s, limit: int = 120) -> str:
    """Trim untrusted text fields before escaping into the email layout."""
    return (s or "").strip()[:limit]


def _li(text: str, count: Optional[int] = None) -> str:
    badge = (
        f'<span style="display:inline-block;background:#A855F7;color:white;font-size:10px;padding:2px 6px;'
        f'border-radius:3px;margin-left:6px;font-weight:bold;letter-spacing:0.5px;">{count} coaches</span>'
        if count is not None else ""
    )
    return (
        f'<li style="padding:6px 0;color:#222;line-height:1.45;">'
        f'<span>{_escape(_safe_text(text))}</span>{badge}</li>'
    )


def _bar_row(label: str, count: int, total: int, color: str) -> str:
    pct = round((count / total) * 100) if total else 0
    return (
        '<tr>'
        f'<td style="font-size:13px;color:#333;padding:6px 8px 4px 0;width:160px;vertical-align:top;">{_escape(_safe_text(label, 40))}</td>'
        '<td style="padding:6px 0 4px 0;vertical-align:top;">'
        '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;">'
        '<tr>'
        f'<td style="background:#EEEEEE;height:14px;border-radius:2px;overflow:hidden;">'
        f'<div style="background:{color};height:14px;width:{pct}%;border-radius:2px;"></div>'
        '</td>'
        f'<td style="padding-left:8px;font-size:12px;color:#666;width:60px;text-align:right;">{count} ({pct}%)</td>'
        '</tr></table></td></tr>'
    )


def render_coach_pulse_email(
    coach_name: str,
    week_label: str,
    network_ready: bool,
    network: dict,
    personal: dict,
    unsubscribe_url: str,
) -> tuple[str, str]:
    """Returns (subject, html). `network` and `personal` are dicts shaped by the route."""
    subject = f"Coach Pulse — {week_label}"

    # Personal section
    p_matches = personal.get("matches", 0)
    p_clips = personal.get("clips", 0)
    p_markers = personal.get("markers", 0)
    p_annotations = personal.get("annotations", 0)

    personal_block = (
        '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:24px;">'
        '<tr><td style="font-size:11px;letter-spacing:2px;color:#888;text-transform:uppercase;font-weight:bold;padding-bottom:8px;">Your week</td></tr>'
        '<tr><td>'
        '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;">'
        '<tr>'
        f'{_stat_cell(p_matches, "matches")}'
        f'{_stat_cell(p_clips, "clips")}'
        f'{_stat_cell(p_markers, "AI markers")}'
        f'{_stat_cell(p_annotations, "notes")}'
        '</tr>'
        '</table>'
        '</td></tr>'
        '</table>'
    )

    if not network_ready:
        network_block = (
            '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:24px;'
            'background:#F5F1FF;border-left:3px solid #A855F7;">'
            '<tr><td style="padding:14px 16px;">'
            '<div style="font-size:11px;letter-spacing:2px;color:#A855F7;text-transform:uppercase;font-weight:bold;margin-bottom:6px;">Coach Network</div>'
            '<div style="font-size:13px;color:#444;line-height:1.5;">'
            'Network insights unlock once 3+ coaches have generated match insights or player ratings on the platform. '
            'Keep uploading — you\'ll see anonymized themes here next week.'
            '</div></td></tr></table>'
        )
    else:
        weaknesses = network.get("common_weaknesses_across_coaches") or []
        strengths = network.get("common_strengths_across_coaches") or []
        positions = network.get("position_breakdown") or []
        recruit_levels = network.get("recruit_level_distribution") or []

        weak_html = "".join(_li(w["text"], w.get("count")) for w in weaknesses[:5]) or '<li style="color:#888;font-size:13px;padding:6px 0;">No recurring weaknesses yet</li>'
        strong_html = "".join(_li(s["text"], s.get("count")) for s in strengths[:5]) or '<li style="color:#888;font-size:13px;padding:6px 0;">No recurring strengths yet</li>'

        pos_total = sum(p["count"] for p in positions) if positions else 0
        pos_html = "".join(_bar_row(p["position"], p["count"], pos_total, "#007AFF") for p in positions[:5]) if pos_total else ""

        rec_total = sum(r["count"] for r in recruit_levels) if recruit_levels else 0
        rec_html = "".join(_bar_row(r["level"], r["count"], rec_total, "#A855F7") for r in recruit_levels[:6]) if rec_total else ""

        platform = network.get("platform", {})
        coaches_count = platform.get("coaches", 0)
        teams_count = platform.get("teams", 0)
        clips_count = platform.get("clips", 0)

        network_block = f"""
        <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:24px;">
          <tr><td style="font-size:11px;letter-spacing:2px;color:#A855F7;text-transform:uppercase;font-weight:bold;padding-bottom:6px;">Coach Network — anonymized</td></tr>
          <tr><td style="font-size:12px;color:#666;padding-bottom:14px;">{coaches_count} coaches · {teams_count} teams · {clips_count} clips analyzed</td></tr>
        </table>

        <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:6px;">
          <tr><td style="font-size:13px;color:#EF4444;font-weight:bold;padding-bottom:4px;">Top weaknesses across coaches</td></tr>
          <tr><td><ul style="margin:0;padding:0 0 0 18px;list-style:disc;">{weak_html}</ul></td></tr>
        </table>

        <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:18px;">
          <tr><td style="font-size:13px;color:#10B981;font-weight:bold;padding-bottom:4px;">Top strengths across coaches</td></tr>
          <tr><td><ul style="margin:0;padding:0 0 0 18px;list-style:disc;">{strong_html}</ul></td></tr>
        </table>

        {('<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:18px;">'
          '<tr><td style="font-size:13px;color:#007AFF;font-weight:bold;padding-bottom:6px;">Player positions on the platform</td></tr>'
          f'<tr><td><table cellpadding="0" cellspacing="0" border="0" style="width:100%;">{pos_html}</table></td></tr>'
          '</table>') if pos_html else ''}

        {('<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:18px;">'
          '<tr><td style="font-size:13px;color:#A855F7;font-weight:bold;padding-bottom:6px;">Recruiter-level distribution</td></tr>'
          f'<tr><td><table cellpadding="0" cellspacing="0" border="0" style="width:100%;">{rec_html}</table></td></tr>'
          '</table>') if rec_html else ''}
        """

    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#F7F7F7;">
  <table cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#F7F7F7;padding:32px 0;">
    <tr><td align="center">
      <table cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:100%;background:white;padding:36px;">
        <tr><td>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
            <span style="display:inline-block;font-size:18px;font-weight:900;letter-spacing:-0.5px;color:#0F1B3D;">Soccer Scout <span style="color:#007AFF;">11</span></span>
          </div>
          <div style="font-size:11px;letter-spacing:3px;color:#A855F7;text-transform:uppercase;font-weight:bold;">Coach Pulse</div>
          <h1 style="margin:6px 0 4px 0;font-size:24px;color:#111;font-weight:bold;letter-spacing:-0.4px;">Hi {_escape(coach_name)}</h1>
          <div style="font-size:13px;color:#888;margin-bottom:8px;">Your weekly digest — {_escape(week_label)}</div>

          {personal_block}
          {network_block}

          <div style="margin-top:32px;border-top:1px solid #EEE;padding-top:18px;font-size:11px;color:#999;line-height:1.6;">
            All cross-coach themes are aggregated and anonymized. Individual matches, players, and coaches are never named.<br>
            <a href="{_escape(unsubscribe_url)}" style="color:#999;text-decoration:underline;">Unsubscribe from Coach Pulse</a>
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
"""
    return subject, html


def _stat_cell(value: int, label: str) -> str:
    return (
        '<td align="center" style="padding:12px 8px;background:#FAFAFA;border:1px solid #EEE;width:25%;">'
        f'<div style="font-size:24px;font-weight:bold;color:#111;">{value}</div>'
        f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-top:2px;">{_escape(label)}</div>'
        '</td>'
    )
