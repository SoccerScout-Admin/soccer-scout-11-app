"""
Login rate-limiter (iter55) — MongoDB-backed sliding-window brute-force defender.

Why MongoDB instead of in-memory? Our preview pod gets reinitialized every few
days due to ephemeral storage exhaustion (see iter51 disk-pressure notes). An
in-memory limiter loses state on every restart, letting attackers reset their
budget by waiting for a crash. MongoDB persists across pod lifecycles.

Why two keys (IP + email)? A bot using rotating proxies hits a different IP
on every attempt → per-IP limit never trips. A per-email limit catches that
case. A per-IP limit catches the inverse (one attacker fanning out across
many usernames). Both apply together — whichever fires first wins.

Public surface:
    check_login_attempt(request, email)       # raises 429 if locked out
    record_failed_login(request, email)       # called from the login handler after a wrong-password check
    record_successful_login(request, email)   # clears both counters on a good login
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 15 * 60  # 15-min sliding window
MAX_ATTEMPTS = 10  # legitimate users typing a wrong password 3-4 times shouldn't trip; bots blowing through 10 will


def _real_client_ip(request: Request) -> str:
    """Resolve the real client IP behind Cloudflare / ingress.

    Order of preference:
      1. `CF-Connecting-IP` — Cloudflare's authoritative header (impossible to spoof
         from outside CF because CF rewrites it on every request)
      2. Leftmost `X-Forwarded-For` entry — standard proxy chain leftmost is the
         original client. Cloudflare strips any spoofed XFF from inbound requests.
      3. `request.client.host` — direct connection (local/dev)

    Returns "unknown" only if all three are absent (shouldn't happen in prod).
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _prune_window(attempts: list, cutoff: datetime) -> list:
    """Return only attempts inside the active window.

    MongoDB's BSON datetime decoder returns offset-naive datetimes by default
    (the motor codec doesn't auto-attach tzinfo). We re-attach UTC on read so
    comparisons with our offset-aware `cutoff` don't blow up.
    """
    def _as_utc(dt):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    return [_as_utc(a) for a in attempts if _as_utc(a) >= cutoff]


async def ensure_login_attempts_indexes(db) -> None:
    """Indexes needed for the limiter — call once at app startup.

    - `key` unique: required for atomic upserts (one doc per IP or per email)
    - `last_attempt_at` TTL after 30 min: docs auto-delete once stale (the
       window is 15 min, the extra 15 buffers against clock skew).
    """
    await db.login_attempts.create_index("key", unique=True)
    await db.login_attempts.create_index(
        "last_attempt_at",
        expireAfterSeconds=30 * 60,  # 2x the window, generous buffer for clock skew
        name="ttl_last_attempt_at",
    )


async def _read_window(db, key: str, now: datetime) -> tuple[list, int]:
    """Return (active_attempts_in_window, count). Empty list if no doc."""
    doc = await db.login_attempts.find_one({"key": key}, {"_id": 0, "attempts": 1})
    if not doc:
        return [], 0
    cutoff = now - timedelta(seconds=WINDOW_SECONDS)
    pruned = _prune_window(doc.get("attempts", []), cutoff)
    return pruned, len(pruned)


async def check_login_attempt(request: Request, email: str, db) -> None:
    """Raise HTTPException(429) if EITHER the IP OR the email is over the
    threshold. Call this BEFORE doing the password bcrypt check — that way an
    attacker can't even exercise the (slow) bcrypt compare once they're locked
    out, removing both timing-attack and DoS vectors.
    """
    now = datetime.now(timezone.utc)
    ip = _real_client_ip(request)
    email_norm = (email or "").lower().strip()

    # Check both keys in parallel — but motor doesn't auto-parallelize awaits
    # in this code path, so sequential is fine. The 2 reads happen on indexed
    # `key` unique lookups → <1ms each.
    for label, key in (("ip", f"ip:{ip}"), ("email", f"email:{email_norm}")):
        if not email_norm and label == "email":
            continue
        attempts_in_window, count = await _read_window(db, key, now)
        if count >= MAX_ATTEMPTS:
            # Compute the wait time so the frontend can show "try again in N min".
            # `_prune_window` already normalized everything to UTC-aware.
            oldest = min(attempts_in_window) if attempts_in_window else now
            retry_after_s = max(1, int(WINDOW_SECONDS - (now - oldest).total_seconds()))
            logger.warning(f"[ratelimit] BLOCKED login by {label}={key} — {count} attempts, retry_after={retry_after_s}s")
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Too many failed login attempts. "
                    f"Try again in {max(1, retry_after_s // 60)} minute"
                    f"{'s' if retry_after_s > 119 else ''}."
                ),
                headers={"Retry-After": str(retry_after_s)},
            )


async def _increment(db, key: str, now: datetime) -> None:
    """Append `now` to the attempts array for this key, prune stale entries,
    update last_attempt_at for TTL. Atomic upsert."""
    cutoff = now - timedelta(seconds=WINDOW_SECONDS)
    existing = await db.login_attempts.find_one({"key": key}, {"_id": 0, "attempts": 1})
    pruned = _prune_window(existing.get("attempts", []) if existing else [], cutoff)
    pruned.append(now)
    await db.login_attempts.update_one(
        {"key": key},
        {"$set": {"attempts": pruned, "last_attempt_at": now}},
        upsert=True,
    )


async def record_failed_login(request: Request, email: str, db) -> None:
    """Bump both the IP counter and the email counter for this failed attempt.
    Both must be incremented so each defends its own attack vector."""
    now = datetime.now(timezone.utc)
    ip = _real_client_ip(request)
    email_norm = (email or "").lower().strip()
    await _increment(db, f"ip:{ip}", now)
    if email_norm:
        await _increment(db, f"email:{email_norm}", now)


async def record_successful_login(request: Request, email: str, db) -> None:
    """On a successful login we delete BOTH counter docs. A legitimate user
    who finally remembered their password resets the threshold for everyone
    on that IP and for that email — the threat is gone."""
    ip = _real_client_ip(request)
    email_norm = (email or "").lower().strip()
    await db.login_attempts.delete_many({"key": {"$in": [f"ip:{ip}", f"email:{email_norm}"]}})
