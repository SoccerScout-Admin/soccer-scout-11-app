"""
Tests for iter65: hourly pipeline-health alert (services/processing_alerts.py).

The alert helper runs once an hour, computes last-hour failure rate, and
Resend-emails the admin if:
  - At least MIN_ATTEMPTS_FOR_ALERT (default 3) final_* events in the window
  - failure_rate_pct >= FAILURE_RATE_THRESHOLD_PCT (default 20%)
  - We haven't already alerted in the past ALERT_DEDUP_WINDOW_HOURS (default 6h)
    UNLESS the rate is materially worse (>= ESCALATION_RATE_DELTA_PCT, default 10pt)

All four branches need test coverage so a future change doesn't accidentally
flood the admin's inbox or, worse, silently swallow real alerts.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pymongo import MongoClient
from dotenv import load_dotenv

from tests.conftest import run_async

load_dotenv()


def _sync_db():
    """Tests seed events directly with pymongo (sync) so we don't fight with
    Motor's loop binding — the conftest's shared loop and Motor's default
    loop are different objects, and Motor + run_async mix raises 'future
    belongs to a different loop'. pymongo bypasses that entirely.

    The SUT (services/processing_alerts.py) still uses Motor in its OWN loop,
    via `from db import db`; only the test fixtures use this sync handle.
    """
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_events(events):
    _sync_db().processing_events.insert_many(events)


def _clear_sentinel(video_id):
    _sync_db().processing_events.delete_many({"video_id": video_id})


def _clear_all_alerts():
    _sync_db().processing_alerts.delete_many({"_kind": "rate_alert"})


def _mk_event(video_id, event_type, failure_mode=None, mins_ago=10):
    return {
        "id": str(uuid.uuid4()),
        "video_id": video_id,
        "user_id": "u-test",
        "event_type": event_type,
        "tier_idx": 0,
        "tier_label": "test",
        "failure_mode": failure_mode,
        "source_size_gb": 1.0,
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=mins_ago)).isoformat(),
    }


@pytest.fixture(autouse=True)
def _fresh_alerts_state():
    """Each test starts with a clean alerts collection so dedup doesn't bleed
    between tests."""
    _clear_all_alerts()
    yield
    _clear_all_alerts()


def test_skip_low_volume(monkeypatch):
    """Fewer than MIN_ATTEMPTS_FOR_ALERT events → skip silently."""
    from services import processing_alerts as svc
    sentinel = f"sentinel-{uuid.uuid4()}"
    _seed_events([_mk_event(sentinel, "final_failure", failure_mode="oom", mins_ago=5)])
    try:
        result = run_async(svc.check_and_alert())
        assert result["action"] == "skip_low_volume"
    finally:
        _clear_sentinel(sentinel)


def test_skip_below_threshold(monkeypatch):
    """Healthy day — 5 successes + 1 failure = 16.7% < 20%. No alert."""
    from services import processing_alerts as svc
    sentinel = f"sentinel-{uuid.uuid4()}"
    events = [_mk_event(sentinel, "final_success", mins_ago=5) for _ in range(5)]
    events.append(_mk_event(sentinel, "final_failure", failure_mode="oom", mins_ago=5))
    _seed_events(events)
    try:
        result = run_async(svc.check_and_alert())
        assert result["action"] == "skip_below_threshold"
        assert result["failure_rate_pct"] < 20
    finally:
        _clear_sentinel(sentinel)


def test_alert_fires_when_threshold_crossed(monkeypatch):
    """2 success + 3 failure = 60% → alert. Email send is mocked so the test
    doesn't actually call Resend."""
    from services import processing_alerts as svc
    sentinel = f"sentinel-{uuid.uuid4()}"
    events = [_mk_event(sentinel, "final_success", mins_ago=5) for _ in range(2)]
    events += [_mk_event(sentinel, "final_failure", failure_mode="oom", mins_ago=5) for _ in range(3)]
    _seed_events(events)

    sent = []
    async def fake_send(*, to_email, subject, html):
        sent.append({"to": to_email, "subject": subject})
        return {"status": "sent"}
    monkeypatch.setattr(svc, "send_or_queue", fake_send)
    # Make sure ALERT_RECIPIENT_EMAIL is set so the alert isn't skipped
    monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "test-alert@example.com")

    try:
        result = run_async(svc.check_and_alert())
        assert result["action"] == "alert_sent"
        assert result["recipient"] == "test-alert@example.com"
        assert len(sent) == 1
        assert "Pipeline failure rate" in sent[0]["subject"]
    finally:
        _clear_sentinel(sentinel)


def test_dedup_within_window(monkeypatch):
    """Two back-to-back checks with the same conditions must NOT fire twice
    (admin's inbox would melt)."""
    from services import processing_alerts as svc
    sentinel = f"sentinel-{uuid.uuid4()}"
    events = [_mk_event(sentinel, "final_success", mins_ago=5) for _ in range(2)]
    events += [_mk_event(sentinel, "final_failure", failure_mode="oom", mins_ago=5) for _ in range(3)]
    _seed_events(events)

    sent = []
    async def fake_send(*, to_email, subject, html):
        sent.append({"to": to_email})
        return {"status": "sent"}
    monkeypatch.setattr(svc, "send_or_queue", fake_send)
    monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "test-alert@example.com")

    try:
        first = run_async(svc.check_and_alert())
        assert first["action"] == "alert_sent"

        second = run_async(svc.check_and_alert())
        assert second["action"] == "skip_deduped"
        assert len(sent) == 1, "Resend must only have been called once"
    finally:
        _clear_sentinel(sentinel)


def test_no_recipient_does_not_crash(monkeypatch):
    """If neither ALERT_RECIPIENT_EMAIL nor SENDER_EMAIL is set, the helper
    must NOT raise — just log the would-be alert and skip."""
    from services import processing_alerts as svc
    sentinel = f"sentinel-{uuid.uuid4()}"
    events = [_mk_event(sentinel, "final_failure", failure_mode="oom", mins_ago=5) for _ in range(4)]
    _seed_events(events)

    monkeypatch.delenv("ALERT_RECIPIENT_EMAIL", raising=False)
    monkeypatch.delenv("SENDER_EMAIL", raising=False)

    try:
        result = run_async(svc.check_and_alert())
        assert result["action"] == "skip_no_recipient"
    finally:
        _clear_sentinel(sentinel)


def test_exception_in_compute_does_not_propagate(monkeypatch):
    """Hard guarantee: a bug in _compute_last_hour_stats must NEVER reach the
    background task loop and crash it (the loop has its own try/except too,
    but we want a defense-in-depth)."""
    from services import processing_alerts as svc

    async def explode():
        raise RuntimeError("simulated DB blow-up")
    monkeypatch.setattr(svc, "_compute_last_hour_stats", explode)

    result = run_async(svc.check_and_alert())
    assert result["action"] == "error"
    assert "simulated" in result["error"]
