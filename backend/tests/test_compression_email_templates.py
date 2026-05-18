"""
Unit tests for iter71: the email_compression_help endpoint now branches into
two distinct templates based on `failure_mode`:

  - failure_mode == "incomplete_upload" → re-upload-from-stable-network message
    (the source file is fine; only our copy is broken)
  - everything else → HandBrake compression message
    (the source file is too big for our encoding pod)

These tests poke the pure helper functions in routes/admin.py directly so we
don't need to spin up the full /api/admin/processing-events/email-compression-help
HTTP path. The HTTP-level dedup + admin-only behaviors are already covered by
test_quick_attach_and_compression_email.py.
"""
import os
import sys

# Ensure backend root is on path
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)


def test_parse_chunks_from_error_canonical():
    """The canonical 'Upload incomplete (N of M chunks, P%)' message
    written by services/processing.py must round-trip cleanly."""
    from routes.admin import _parse_chunks_from_error
    available, total = _parse_chunks_from_error(
        "Upload incomplete (980 of 991 chunks, 99.0%). Re-upload required — AI analysis can't run on a partial file."
    )
    assert available == 980
    assert total == 991


def test_parse_chunks_from_error_returns_none_when_unparseable():
    """Defensive: arbitrary error strings shouldn't blow up — they should
    just return (None, None) so the email body falls back to a no-numbers
    message instead of crashing the send."""
    from routes.admin import _parse_chunks_from_error
    assert _parse_chunks_from_error(None) == (None, None)
    assert _parse_chunks_from_error("") == (None, None)
    assert _parse_chunks_from_error("ffmpeg killed by signal 9") == (None, None)


def test_incomplete_upload_html_includes_red_cta_and_progress():
    """The incomplete-upload template must visually distinguish itself from
    the compression template (red header, not blue) AND surface the exact
    chunk progress so the coach knows it's a connection issue, not a file
    issue."""
    from routes.admin import _incomplete_upload_help_html
    html = _incomplete_upload_help_html(
        coach_name="Ben",
        filename="lfc_vs_bowling_green.mp4",
        size_gb=9.67,
        available=980,
        total=991,
    )
    # Red header (vs the blue #007AFF compression header)
    assert "#EF4444" in html
    assert "Upload Interrupted" in html
    # The chunk progress must be baked into the body. 980/991 = 98.88...%
    # which rounds to 98.9% (1 decimal place) — sanity-check the helper's
    # rounding instead of hard-coding the wrong number.
    assert "980 of 991 chunks" in html
    assert "98.9%" in html
    # The CTA points to the in-product red button (added in iter70)
    assert "DELETE &amp; RE-UPLOAD" in html or "DELETE & RE-UPLOAD" in html
    # The message must clearly reassure the coach that THEIR file is fine
    assert "original file on your computer is fine" in html
    # And must NOT recommend HandBrake compression as the primary fix
    # (it's only mentioned as a secondary tip)
    first_paragraph = html.split("</p>")[1]
    assert "HandBrake" not in first_paragraph


def test_incomplete_upload_html_falls_back_without_chunk_numbers():
    """When the chunk parse fails, the email still sends with a generic
    'upload got interrupted' message — never crashes — and doesn't try to
    fabricate a fake chunk count."""
    from routes.admin import _incomplete_upload_help_html
    html = _incomplete_upload_help_html(
        coach_name=None,
        filename="some_video.mp4",
        size_gb=4.2,
        available=None,
        total=None,
    )
    # Must NOT surface fake "N of M chunks" numbers when we don't have them
    assert "chunks (" not in html  # the canonical "N of M chunks (P%)" pattern
    # But the size fallback IS there
    assert "4.2 GB" in html
    # And the generic interruption message
    assert "upload got interrupted" in html


def test_compression_html_recommends_handbrake():
    """The 'file too big' template must still recommend HandBrake with
    the exact Fast 720p30 / CQ 28 settings used by our iter63 retry tier."""
    from routes.admin import _compression_help_html
    html = _compression_help_html(
        coach_name="Coach",
        filename="huge.mp4",
        size_gb=8.5,
        failure_mode="oom",
    )
    assert "HandBrake" in html
    assert "Fast 720p30" in html
    assert "CQ" in html and "28" in html
    # Blue header (not red)
    assert "#007AFF" in html
    # Must NOT use the incomplete-upload red header
    assert "Upload Interrupted" not in html


def test_html_templates_handle_no_name():
    """Both templates must work without a coach_name (graceful greeting)."""
    from routes.admin import _compression_help_html, _incomplete_upload_help_html
    h1 = _compression_help_html(None, "f.mp4", 1.0, "oom")
    h2 = _incomplete_upload_help_html(None, "f.mp4", 1.0, None, None)
    assert "Hi there," in h1
    assert "Hi there," in h2
    # Neither should leak a literal "None" into the body
    assert "Hi None" not in h1
    assert "Hi None" not in h2
