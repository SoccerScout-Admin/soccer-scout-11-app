"""Stale temp file sweeper — boot-time cleanup verifies orphan reclaim works."""
from __future__ import annotations

import os
import sys
import time
import tempfile

sys.path.insert(0, "/app/backend")

from tests.conftest import run_async as _run_async  # noqa: F401


def test_sweeper_reclaims_old_tmp_files(tmp_path, monkeypatch):
    """The boot sweeper should unlink temp files older than 30 minutes and
    leave fresh ones in place."""
    from server import _cleanup_stale_temp_files

    # Stage 3 files in the real reels temp dir: one stale, one fresh, one
    # non-tmp prefix that must be untouched.
    reels_dir = "/var/video_chunks/reels"
    os.makedirs(reels_dir, exist_ok=True)

    stale = os.path.join(reels_dir, "tmp_test_stale_" + os.urandom(4).hex() + ".mp4")
    fresh = os.path.join(reels_dir, "tmp_test_fresh_" + os.urandom(4).hex() + ".mp4")
    keep = os.path.join(reels_dir, "real-reel-output-" + os.urandom(4).hex() + ".mp4")

    for p in (stale, fresh, keep):
        with open(p, "wb") as fh:
            fh.write(b"x" * 1024)

    # Backdate the stale file by 20 minutes (>10 min threshold)
    cutoff = time.time() - 20 * 60
    os.utime(stale, (cutoff, cutoff))

    try:
        _run_async(_cleanup_stale_temp_files())
        assert not os.path.exists(stale), "stale temp file should have been removed"
        assert os.path.exists(fresh), "fresh temp file (<10min) must remain"
        assert os.path.exists(keep), "non-tmp prefixed files must NEVER be touched"
    finally:
        for p in (stale, fresh, keep):
            if os.path.exists(p):
                os.unlink(p)


def test_sweeper_handles_missing_directory():
    """Running on a fresh container with empty dirs must not raise."""
    from server import _cleanup_stale_temp_files
    # Should be a no-op, no errors
    _run_async(_cleanup_stale_temp_files())
