"""
iter105 — Pod memory chip + one-click Support escalation.

User confirmed 2026-05-28: Production probe returned
`verdict: "4gb-or-smaller-pod-needs-support-bump"` despite Support promising
a bump to 20 GB last week. iter105 surfaces the live memory probe on the
Storage Cleanup admin page with a color-coded chip + a "Request pod bump"
button that drafts the escalation email with the JSON evidence baked in.
"""
import os
import sys
import re

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


# ---------------------------------------------------------------------------
# Backend memory probe (iter104) is the data source
# ---------------------------------------------------------------------------

def test_health_memory_endpoint_returns_required_fields():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/memory")
            assert r.status_code == 200
            body = r.json()
            # All fields the frontend chip relies on
            for k in ("cgroup_limit_bytes", "cgroup_limit_gb", "cgroup_path",
                      "process_rss_gb", "host_total_gb", "verdict"):
                assert k in body, f"/api/health/memory missing field: {k}"
            # verdict must be one of the documented buckets
            assert body["verdict"] in (
                "20gb-class-pod-confirmed",
                "8gb-class-pod",
                "4gb-or-smaller-pod-needs-support-bump",
                "unknown",
            )
    _run_async(run())


def test_health_memory_no_auth_required():
    """The probe is meant to be hit by support tickets / health monitors —
    must work without auth."""
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/memory")
            assert r.status_code == 200
    _run_async(run())


# ---------------------------------------------------------------------------
# Frontend wiring on the Storage Cleanup admin page
# ---------------------------------------------------------------------------

def test_admin_page_renders_pod_memory_chip():
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    # Critical testids the chip exposes
    assert 'data-testid="pod-memory-section"' in src
    assert 'data-testid="pod-memory-cgroup-gb"' in src
    # Fetches the probe in the existing Promise.all batch
    assert "/health/memory" in src
    assert "setMemory" in src


def test_admin_page_renders_verdict_specific_messaging():
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    # Each verdict bucket has a tailored explanation
    assert "20gb-class-pod-confirmed" in src
    assert "8gb-class-pod" in src
    assert "4gb-or-smaller-pod-needs-support-bump" in src
    # And distinct color treatment per verdict
    assert "#10B981" in src  # green for 20gb
    assert "#FBBF24" in src  # yellow for 8gb
    assert "#EF4444" in src  # red for 4gb


def test_admin_page_pod_bump_button_only_for_4gb_verdict():
    """The escalation button must ONLY render on the 4 GB verdict so users
    on healthy pods don't see a misleading 'something is wrong' button."""
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    assert 'data-testid="pod-bump-email-btn"' in src
    # The button is gated by the 4gb verdict check
    btn_idx = src.find('data-testid="pod-bump-email-btn"')
    # Walk back ~500 chars to find the conditional
    surrounding = src[max(0, btn_idx - 500):btn_idx]
    assert "4gb-or-smaller-pod-needs-support-bump" in surrounding, (
        "pod-bump button must be conditionally rendered on the 4gb verdict"
    )


def test_admin_page_drafts_pod_bump_email_with_probe_data():
    """The mailto body must include the actual probe JSON so support can
    verify the bump didn't land — not just a generic 'please bump my pod'."""
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    assert "handleCopyPodBumpEmail" in src
    # Email body must reference the probe fields
    assert "cgroup_limit_gb" in src
    assert "process_rss_gb" in src
    assert "verdict:" in src or "verdict =" in src
    # Must target the right inbox + a Subject that gets routed to the pod team
    assert "support@emergent.sh" in src
    assert "Pod memory bump" in src or "pod memory bump" in src.lower()


def test_admin_page_pod_bump_button_copies_to_clipboard():
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    # navigator.clipboard fallback in case mailto doesn't open the user's
    # mail client (webmail users)
    assert "navigator.clipboard.writeText" in src
    # mailto: scheme is also wired
    assert "mailto:support@emergent.sh" in src


# ---------------------------------------------------------------------------
# Deploy endpoint advertises iter105 feature flags
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter105_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            body = r.json()
            m = re.match(r'iter(\d+)', body["build"] or "")
            assert m and int(m.group(1)) >= 105
            features = set(body["features"])
            assert "pod-memory-chip-storage-cleanup-page" in features
            assert "pod-bump-support-email-draft" in features
            assert "pod-verdict-color-coded-status" in features
    _run_async(run())
