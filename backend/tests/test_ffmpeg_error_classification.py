"""
Tests for iter62: ffmpeg error classification in prepare_video_sample.

The pre-iter62 error path dumped the raw ffmpeg command (truncated at 200
chars) which buried the real failure cause. Production users hit this on a
1.75 GB upload — they saw "Failed to prepare video: Command '[ffmpeg, -y,
-i, ...]'" with no indication whether it was timeout, OOM, or a corrupt
input file.

This suite locks in the classification logic so future regressions are
caught early.
"""
import subprocess
from unittest.mock import MagicMock
import pytest

from tests.conftest import run_async


def _wire_fake_filesystem(monkeypatch, svc, tmp_path, fake_size_gb):
    """Bypass the chunk-assembly + tempfile + disk-usage paths so we can drive
    prepare_video_sample straight to its ffmpeg invocation. Each test then
    only has to monkeypatch subprocess.run with the failure mode it cares
    about."""
    fake_raw = tmp_path / "raw.mp4"
    fake_raw.write_bytes(b"\x00" * 1024)

    mktemp_calls = {"n": 0}

    def fake_mktemp(**kw):
        mktemp_calls["n"] += 1
        # First call → raw path; second → clip path
        if mktemp_calls["n"] == 1:
            return str(fake_raw)
        return str(tmp_path / f"clip{kw.get('suffix', '')}")

    monkeypatch.setattr(svc, "get_object_sync", lambda p: (b"\x00" * 1024, "video/mp4"))
    monkeypatch.setattr(svc.tempfile, "mktemp", fake_mktemp)
    monkeypatch.setattr(svc.os.path, "getsize", lambda p: int(fake_size_gb * 1024 ** 3))

    async def call_directly(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(svc, "run_in_threadpool", call_directly)


def _fake_video():
    return {
        "id": "test-video",
        "is_chunked": False,
        "storage_path": "test/path",
        "original_filename": "match.mp4",
    }


def test_timeout_message_is_actionable(monkeypatch, tmp_path):
    """subprocess.TimeoutExpired must surface as a coach-friendly message,
    NOT as the default "Command [...] timed out after 1800 seconds" dump
    that includes the entire ffmpeg argv (which gets truncated and hides
    the real cause).
    """
    from services import processing as svc
    _wire_fake_filesystem(monkeypatch, svc, tmp_path, fake_size_gb=1.5)

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1800)
    monkeypatch.setattr(svc.subprocess, "run", raise_timeout)

    with pytest.raises(Exception) as exc_info:
        run_async(svc.prepare_video_sample(_fake_video()))

    msg = str(exc_info.value).lower()
    assert "timed out" in msg
    assert "30 min" in msg or "30-min" in msg
    # Must give the coach a path forward — not just "error".
    assert any(hint in msg for hint in ["trim", "compress", "handbrake", "720p", "cq 28"])


def test_sigkill_returns_oom_message(monkeypatch, tmp_path):
    """ffmpeg killed by SIGKILL (rc=-9 or 137) means pod OOM. Surface a
    "your file is too big for current pod memory" message so the coach
    knows to compress further, not retry blindly."""
    from services import processing as svc
    _wire_fake_filesystem(monkeypatch, svc, tmp_path, fake_size_gb=1.75)

    fake_result = MagicMock(returncode=-9, stderr="signal received\nKilled\n")
    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **k: fake_result)

    with pytest.raises(Exception) as exc_info:
        run_async(svc.prepare_video_sample(_fake_video()))

    msg = str(exc_info.value).lower()
    assert "memory" in msg or "oom" in msg
    assert "compress" in msg or "split" in msg


def test_moov_missing_message_unchanged(monkeypatch, tmp_path):
    """Existing moov-atom detection must still work — chunked uploads that
    finalize before all chunks arrive produce this."""
    from services import processing as svc
    _wire_fake_filesystem(monkeypatch, svc, tmp_path, fake_size_gb=1.0)

    fake_result = MagicMock(returncode=1, stderr="some ffmpeg blather\nmoov atom not found\n")
    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **k: fake_result)

    with pytest.raises(Exception) as exc_info:
        run_async(svc.prepare_video_sample(_fake_video()))

    msg = str(exc_info.value).lower()
    assert "moov atom" in msg
    assert "re-upload" in msg


def test_no_space_message(monkeypatch, tmp_path):
    """Disk full during encode → clear "retry in a few minutes" hint."""
    from services import processing as svc
    _wire_fake_filesystem(monkeypatch, svc, tmp_path, fake_size_gb=1.0)

    fake_result = MagicMock(returncode=1, stderr="av_interleaved_write_frame: No space left on device\n")
    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **k: fake_result)

    with pytest.raises(Exception) as exc_info:
        run_async(svc.prepare_video_sample(_fake_video()))

    msg = str(exc_info.value).lower()
    assert "disk" in msg
    assert "retry" in msg


def test_unclassified_error_shows_stderr_tail_not_command(monkeypatch, tmp_path):
    """Catch-all path: when no known pattern matches, the message must show
    the END of stderr (where ffmpeg writes the actual error) rather than
    leaking the raw command/args/argv. Pre-iter62 the user saw the head of
    the ffmpeg argv which was useless."""
    from services import processing as svc
    _wire_fake_filesystem(monkeypatch, svc, tmp_path, fake_size_gb=1.0)

    stderr_blob = (
        "ffmpeg version 4.4.2 (lots of header info goes here)\n"
        "Input #0, mov,mp4,m4a,3gp,3g2,mj2 ...\n"
        "Some intermediate noise the user doesn't need\n"
        "Conversion failed!\n"
    )
    fake_result = MagicMock(returncode=1, stderr=stderr_blob)
    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **k: fake_result)

    with pytest.raises(Exception) as exc_info:
        run_async(svc.prepare_video_sample(_fake_video()))

    msg = str(exc_info.value)
    # Final stderr line (tail) shows up, NOT the ffmpeg command.
    assert "Conversion failed" in msg
    assert "ffmpeg" in msg.lower()
    # Make sure we're not just leaking the command argv as before.
    assert "-vf" not in msg
    assert "libx264" not in msg
