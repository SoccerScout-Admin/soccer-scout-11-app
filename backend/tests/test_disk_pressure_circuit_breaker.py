"""
Tests for the disk-pressure circuit breaker (iter51).

The breaker has two triggers:
  1. Used % >= 80%
  2. Free bytes - incoming bytes < 2 GB reserve

Both must raise HTTPException(503) with a clear Retry-After header.
A healthy disk (well below thresholds) must not block.
"""
from unittest.mock import patch
import pytest
from fastapi import HTTPException

from server import _check_disk_pressure


def _mock_disk(total_gb: float, used_gb: float):
    """Helper that returns a (total, used, free) tuple in bytes for shutil.disk_usage mock."""
    total = int(total_gb * 1024 ** 3)
    used = int(used_gb * 1024 ** 3)
    free = total - used
    return (total, used, free)


def test_healthy_disk_does_not_block():
    """50% used + 50GB free = pass through."""
    with patch("shutil.disk_usage", return_value=_mock_disk(total_gb=100, used_gb=50)):
        # Should not raise
        _check_disk_pressure(incoming_bytes=0)
        _check_disk_pressure(incoming_bytes=10 * 1024 ** 3)


def test_blocks_at_threshold():
    """Used % >= 80% triggers the breaker regardless of incoming size."""
    with patch("shutil.disk_usage", return_value=_mock_disk(total_gb=100, used_gb=80)):
        with pytest.raises(HTTPException) as exc:
            _check_disk_pressure(incoming_bytes=0)
        assert exc.value.status_code == 503
        assert "Retry-After" in exc.value.headers
        assert exc.value.headers["Retry-After"] == "300"
        # Friendly user-facing message — should mention retry
        assert "try" in exc.value.detail.lower()


def test_blocks_when_incoming_eats_reserve():
    """50% used (50GB free) but a 49GB upload would leave only 1GB free → blocked."""
    with patch("shutil.disk_usage", return_value=_mock_disk(total_gb=100, used_gb=50)):
        with pytest.raises(HTTPException) as exc:
            _check_disk_pressure(incoming_bytes=49 * 1024 ** 3)
        assert exc.value.status_code == 503


def test_allows_when_incoming_leaves_reserve():
    """50% used (50GB free), 30GB upload still leaves 20GB → fine."""
    with patch("shutil.disk_usage", return_value=_mock_disk(total_gb=100, used_gb=50)):
        # Should not raise
        _check_disk_pressure(incoming_bytes=30 * 1024 ** 3)


def test_blocks_at_exact_threshold_boundary():
    """80.0% should block (>=), not just 80.1%+."""
    with patch("shutil.disk_usage", return_value=_mock_disk(total_gb=100, used_gb=80)):
        with pytest.raises(HTTPException):
            _check_disk_pressure(incoming_bytes=0)


def test_just_under_threshold_passes():
    """79.9% with healthy free space → pass."""
    with patch("shutil.disk_usage", return_value=_mock_disk(total_gb=100, used_gb=79.5)):
        _check_disk_pressure(incoming_bytes=0)


def test_failopen_when_disk_usage_errors():
    """If shutil.disk_usage itself raises, we must NOT block uploads — failing
    open is safer than locking everyone out due to a stat call hiccup."""
    with patch("shutil.disk_usage", side_effect=OSError("simulated")):
        # Should not raise — fails open
        _check_disk_pressure(incoming_bytes=10 * 1024 ** 3)
