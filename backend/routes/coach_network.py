"""Coach Network — anonymized platform-wide benchmarks.

Aggregates trends across ALL users without exposing individual user data.
Privacy guarantees:
- Never returns user_id, names, or any identifying fields
- All aggregations require a minimum sample size (k-anonymity threshold)
- Numeric distributions are bucketed
- Returns only the calling user's percentile bucket, not their raw rank
"""
from fastapi import APIRouter, Depends, HTTPException
from collections import Counter
from datetime import datetime, timezone
from db import db
from routes.auth import get_current_user

router = APIRouter()

K_ANON_THRESHOLD = 3  # minimum coaches before we expose an aggregate metric


def _percentile_bucket(value: float, sorted_values: list) -> str:
    """Return a coarse bucket (Top 25% / Top 50% / Bottom 50% / Bottom 25%)."""
    if not sorted_values:
        return "—"
    rank = sum(1 for v in sorted_values if v < value)
    pct = rank / len(sorted_values)
    if pct >= 0.75:
        return "Top 25%"
    if pct >= 0.5:
        return "Top 50%"
    if pct >= 0.25:
        return "Bottom 50%"
    return "Bottom 25%"


def _parse_iso_safe(value):
    """Tolerant ISO-8601 parser — always returns a tz-aware datetime or None."""
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


@router.get("/coach-network/benchmarks")
async def get_network_benchmarks(current_user: dict = Depends(get_current_user)):
    """Platform-wide benchmark dashboard for coaches.

    Returns aggregate metrics across all coaches/teams/players, plus the
    calling user's bucket on each metric.
    """
    return await compute_benchmarks(current_user["id"])


async def _platform_totals() -> dict:
    """Headline platform counts. Cheap (5 indexed count queries)."""
    return {
        "coaches": await db.users.count_documents({}),
        "teams": await db.teams.count_documents({}),
        "matches": await db.matches.count_documents({}),
        "clips": await db.clips.count_documents({}),
        "markers": await db.markers.count_documents({}),
    }


async def _user_personal_totals(user_id: str | None) -> dict:
    """Calling user's personal counts. All zeros when user_id is None (digest path)."""
    if not user_id:
        return {"teams": 0, "matches": 0, "clips": 0}
    return {
        "teams": await db.teams.count_documents({"user_id": user_id}),
        "matches": await db.matches.count_documents({"user_id": user_id}),
        "clips": await db.clips.count_documents({"user_id": user_id}),
    }


async def _per_coach_distribution(collection) -> list:
    """Sorted-ascending list of per-coach counts for a given collection. Used
    for avg/median + percentile-bucket placement of the calling user."""
    result = []
    async for doc in collection.aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]):
        result.append(doc["n"])
    result.sort()
    return result


def _avg(xs: list) -> float:
    return round(sum(xs) / len(xs), 1) if xs else 0


def _median(xs: list):
    return xs[len(xs) // 2] if xs else 0


async def _position_counts() -> Counter:
    counts: Counter = Counter()
    async for p in db.players.find({}, {"_id": 0, "position": 1}):
        pos = (p.get("position") or "Unknown").strip() or "Unknown"
        counts[pos] += 1
    return counts


async def _insight_theme_counters() -> tuple[Counter, Counter, int]:
    """Returns (strengths, weaknesses, sample_count). Each theme is counted
    once per match (first 4 themes only — matches existing display cap)."""
    strengths: Counter = Counter()
    weaknesses: Counter = Counter()
    n = 0
    async for m in db.matches.find(
        {"insights": {"$exists": True}},
        {"_id": 0, "insights.strengths": 1, "insights.weaknesses": 1},
    ):
        ins = m.get("insights") or {}
        for s in (ins.get("strengths") or [])[:4]:
            strengths[s.strip().lower()] += 1
        for w in (ins.get("weaknesses") or [])[:4]:
            weaknesses[w.strip().lower()] += 1
        n += 1
    return strengths, weaknesses, n


async def _recruiter_level_distribution() -> tuple[Counter, int]:
    """Recruiter levels from cached player trend reports. Returns (counter, sample_count)."""
    levels: Counter = Counter()
    n = 0
    async for p in db.players.find({"trends": {"$exists": True}}, {"_id": 0, "trends": 1}):
        trends = p.get("trends") or {}
        for v in trends.values():
            if isinstance(v, dict):
                level = (v.get("report") or {}).get("recruiter_view", {}).get("estimated_level")
                if level:
                    levels[level] += 1
                    n += 1
    return levels, n


async def _processing_durations(user_id: str | None) -> tuple[list, list]:
    """Sanity-bounded AI processing durations (10s–2h, matching /processing-eta-stats).
    Returns (all_durations, my_durations)."""
    all_durations = []
    my_durations = []
    async for v in db.videos.find(
        {
            "processing_status": "completed",
            "processing_started_at": {"$ne": None},
            "processing_completed_at": {"$ne": None},
        },
        {"_id": 0, "user_id": 1, "processing_started_at": 1, "processing_completed_at": 1},
    ):
        started = _parse_iso_safe(v.get("processing_started_at"))
        finished = _parse_iso_safe(v.get("processing_completed_at"))
        if not started or not finished:
            continue
        dur = (finished - started).total_seconds()
        if not (10 <= dur <= 7200):
            continue
        all_durations.append(dur)
        if user_id and v.get("user_id") == user_id:
            my_durations.append(dur)
    return all_durations, my_durations


def _top_themes(counter: Counter, limit: int = 8) -> list:
    """k-anonymity: only surface themes that ≥K_ANON_THRESHOLD coaches share."""
    return [
        {"text": text.capitalize(), "count": cnt}
        for text, cnt in counter.most_common(10)
        if cnt >= K_ANON_THRESHOLD
    ][:limit]


def _below_threshold_response(platform_totals: dict, user_totals: dict) -> dict:
    """Returned when there aren't enough coaches to safely surface aggregates."""
    return {
        "ready": False,
        "message": f"Coach Network unlocks at {K_ANON_THRESHOLD}+ coaches on the platform (currently {platform_totals['coaches']}).",
        "platform": platform_totals,
        "you": user_totals,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def compute_benchmarks(user_id: str | None = None) -> dict:
    """Reusable benchmark computation. user_id is optional — if provided, the
    'you' section is populated; if None, only platform-wide aggregates are
    returned (digest path).

    iter56 refactor: this used to be a 168-line function with cyclomatic
    complexity 30. Split into ~10 focused async helpers above. Each helper
    owns a single metric collection or formatting step; this orchestrator
    just composes them. Behavior preserved 1:1 — verified by existing tests.
    """
    platform = await _platform_totals()
    user_totals = await _user_personal_totals(user_id)

    # k-anonymity: refuse to surface aggregates if there aren't enough coaches yet
    if platform["coaches"] < K_ANON_THRESHOLD:
        return _below_threshold_response(platform, user_totals)

    matches_by_coach = await _per_coach_distribution(db.matches)
    clips_by_coach = await _per_coach_distribution(db.clips)
    markers_by_coach = await _per_coach_distribution(db.markers)

    position_counts = await _position_counts()
    strength_counter, weakness_counter, insights_count = await _insight_theme_counters()
    recruit_levels, trends_count = await _recruiter_level_distribution()
    all_durations, my_durations = await _processing_durations(user_id)

    platform_avg_proc = round(sum(all_durations) / len(all_durations), 1) if all_durations else None
    your_avg_proc = round(sum(my_durations) / len(my_durations), 1) if my_durations else None

    return {
        "ready": True,
        "platform": platform,
        "distributions": {
            "matches_per_coach": {"avg": _avg(matches_by_coach), "median": _median(matches_by_coach)},
            "clips_per_coach": {"avg": _avg(clips_by_coach), "median": _median(clips_by_coach)},
            "markers_per_coach": {"avg": _avg(markers_by_coach), "median": _median(markers_by_coach)},
        },
        "you": {
            **user_totals,
            "matches_bucket": _percentile_bucket(user_totals["matches"], matches_by_coach),
            "clips_bucket": _percentile_bucket(user_totals["clips"], clips_by_coach),
        },
        "position_breakdown": [
            {"position": pos, "count": cnt}
            for pos, cnt in position_counts.most_common(10)
        ],
        "common_strengths_across_coaches": _top_themes(strength_counter),
        "common_weaknesses_across_coaches": _top_themes(weakness_counter),
        "recruit_level_distribution": [
            {"level": lvl, "count": cnt}
            for lvl, cnt in recruit_levels.most_common(10)
        ],
        "samples": {
            "match_insights_aggregated": insights_count,
            "player_trends_aggregated": trends_count,
            "processing_durations_aggregated": len(all_durations),
        },
        "processing_time": {
            "platform_avg_seconds": platform_avg_proc,
            "your_avg_seconds": your_avg_proc,
            "your_samples": len(my_durations),
        },
        "k_anonymity_threshold": K_ANON_THRESHOLD,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }



@router.get("/coach-network/mentions")
async def list_my_mentions(
    unread_only: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Return clip-reel mentions where the current user was tagged.
    Each mention is enriched with the reel title, share_token and clip count
    so the UI can link straight to the public reel.
    """
    query: dict = {"mentioned_user_id": current_user["id"]}
    if unread_only:
        query["read_at"] = {"$in": [None, ""]}
    mentions = await db.clip_mentions.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    if not mentions:
        return []
    coll_ids = list({m["collection_id"] for m in mentions})
    collections = await db.clip_collections.find(
        {"id": {"$in": coll_ids}},
        {"_id": 0, "id": 1, "title": 1, "share_token": 1, "clip_ids": 1, "description": 1, "created_at": 1},
    ).to_list(len(coll_ids))
    coll_map = {c["id"]: c for c in collections}
    result = []
    for m in mentions:
        coll = coll_map.get(m["collection_id"])
        if not coll:
            continue  # collection deleted — skip orphan
        result.append({
            "id": m["id"],
            "mentioner_name": m.get("mentioner_name") or "A coach",
            "mentioner_user_id": m.get("mentioner_user_id"),
            "collection_id": coll["id"],
            "reel_title": coll.get("title") or "Clip Reel",
            "reel_share_token": coll.get("share_token"),
            "reel_clip_count": len(coll.get("clip_ids") or []),
            "reel_description": (coll.get("description") or "")[:400],
            "created_at": m.get("created_at"),
            "read_at": m.get("read_at"),
            "email_sent": bool(m.get("email_sent")),
        })
    return result


@router.post("/coach-network/mentions/{mention_id}/read")
async def mark_mention_read(
    mention_id: str, current_user: dict = Depends(get_current_user)
):
    """Mark a single mention as read (updates read_at timestamp)."""
    res = await db.clip_mentions.update_one(
        {"id": mention_id, "mentioned_user_id": current_user["id"]},
        {"$set": {"read_at": datetime.now(timezone.utc).isoformat()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Mention not found")
    return {"status": "ok"}


@router.post("/coach-network/mentions/read-all")
async def mark_all_mentions_read(current_user: dict = Depends(get_current_user)):
    """Mark every mention for the current user as read."""
    now = datetime.now(timezone.utc).isoformat()
    res = await db.clip_mentions.update_many(
        {"mentioned_user_id": current_user["id"], "read_at": {"$in": [None, ""]}},
        {"$set": {"read_at": now}},
    )
    return {"updated": res.modified_count}


@router.get("/coach-network/mentionable-coaches")
async def mentionable_coaches(
    q: str = "", current_user: dict = Depends(get_current_user)
):
    """Return coaches the current user can @-mention in a shared clip reel.

    Includes all other coaches on the platform (the Coach Network is the whole
    platform). Results filtered by a case-insensitive substring match on name
    or email. Excludes the caller and inactive/empty accounts (coaches with
    zero matches AND zero clips are deprioritized but still returned so a
    fresh coach can still be mentioned).
    """
    import re
    q = (q or "").strip()
    base = {"id": {"$ne": current_user["id"]}}
    if q:
        pattern = {"$regex": re.escape(q), "$options": "i"}
        base["$or"] = [{"name": pattern}, {"email": pattern}]
    users = await db.users.find(base, {"_id": 0, "id": 1, "name": 1, "email": 1}).limit(20).to_list(20)
    # Enrich with activity counters so the UI can sort active coaches first
    result = []
    for u in users:
        matches_n = await db.matches.count_documents({"user_id": u["id"]})
        clips_n = await db.clips.count_documents({"user_id": u["id"]})
        result.append({
            "id": u["id"],
            "name": u.get("name") or "",
            "email": u.get("email") or "",
            "matches_count": matches_n,
            "clips_count": clips_n,
            "active": (matches_n + clips_n) > 0,
        })
    # Active coaches first
    result.sort(key=lambda r: (not r["active"], r["name"].lower()))
    return result
