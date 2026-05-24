"""
iter91 — Global Object Storage outage banner.

After the 2026-05-23 21+ hour Emergent Object Storage outage, users had no
proactive signal that uploads would fail — they had to attempt one and hit
the iter90 fail-fast modal. iter91 mounts a top-of-page yellow banner that
polls /api/health/storage every 60s and auto-clears the moment storage
recovers.
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


_BANNER_PATH = os.path.join(
    _BACKEND, "..", "frontend", "src", "components", "StorageOutageBanner.js",
)
_APP_PATH = os.path.join(_BACKEND, "..", "frontend", "src", "App.js")


def test_banner_component_file_exists():
    assert os.path.isfile(_BANNER_PATH), f"{_BANNER_PATH} must exist"


def test_banner_polls_storage_health_endpoint():
    with open(_BANNER_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "/health/storage" in src, "Banner must poll /api/health/storage"
    assert "setInterval" in src, "Banner must use setInterval to re-probe"
    # The poll interval should be 60s or less so users see recovery quickly
    assert "60 * 1000" in src or "60000" in src or "30 * 1000" in src, (
        "Banner poll interval should be 30-60s — fast enough to clear on recovery."
    )


def test_banner_renders_only_when_storage_unhealthy():
    with open(_BANNER_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # The banner must guard rendering on `healthy === false` (or equivalent).
    assert "if (healthy" in src or "if (!healthy" in src, (
        "Banner must short-circuit render when storage is healthy."
    )


def test_banner_has_dismiss_button():
    """Users hitting a long outage should be able to hide the banner for
    the rest of their session."""
    with open(_BANNER_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "data-testid=\"storage-outage-banner-dismiss\"" in src
    assert "dismissed" in src


def test_banner_undismisses_on_recovery():
    """If the user dismissed the banner during an outage and storage then
    RECOVERS, the next outage should show a fresh banner (i.e. dismissed
    state resets on healthy=true)."""
    with open(_BANNER_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # Look for the recovery reset pattern
    assert "setDismissed(false)" in src, (
        "On healthy=true the banner must call setDismissed(false) so a future "
        "outage renders fresh — otherwise a user who dismissed once never sees "
        "subsequent outage banners."
    )


def test_app_mounts_storage_outage_banner():
    with open(_APP_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "StorageOutageBanner" in src
    assert "<StorageOutageBanner" in src, "Banner must be rendered, not just imported."


def test_banner_uses_distinct_color_from_disk_pressure_banner():
    """The disk-pressure banner is red. The storage-outage banner is yellow —
    distinct so users with both visible can tell them apart."""
    with open(_BANNER_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    # Yellow / amber palette
    assert "F59E0B" in src, (
        "Banner should use the yellow (#F59E0B) palette so it's visually "
        "distinct from the red disk-pressure banner."
    )
