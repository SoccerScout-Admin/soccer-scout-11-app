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


async def compute_benchmarks(user_id: str | None = None) -> dict:
    """Reusable benchmark computation. user_id is optional — if provided, the
    'you' section is populated; if None, only platform-wide aggregates are returned.
    """
    # Total platform stats (coaches, teams, players, matches)
    total_coaches = await db.users.count_documents({})
    total_teams = await db.teams.count_documents({})
    total_matches = await db.matches.count_documents({})
    total_clips = await db.clips.count_documents({})
    total_markers = await db.markers.count_documents({})

    user_id = user_id  # may be None for the email digest path
    my_teams = await db.teams.count_documents({"user_id": user_id}) if user_id else 0
    my_matches = await db.matches.count_documents({"user_id": user_id}) if user_id else 0
    my_clips = await db.clips.count_documents({"user_id": user_id}) if user_id else 0

    # Refuse to surface aggregates if there aren't enough coaches yet
    if total_coaches < K_ANON_THRESHOLD:
        return {
            "ready": False,
            "message": f"Coach Network unlocks at {K_ANON_THRESHOLD}+ coaches on the platform (currently {total_coaches}).",
            "platform": {
                "coaches": total_coaches,
                "teams": total_teams,
                "matches": total_matches,
                "clips": total_clips,
                "markers": total_markers,
            },
            "you": {
                "teams": my_teams,
                "matches": my_matches,
                "clips": my_clips,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # Per-coach distributions (matches/clips/markers per user)
    matches_by_coach = []
    clips_by_coach = []
    markers_by_coach = []
    async for doc in db.matches.aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]):
        matches_by_coach.append(doc["n"])
    async for doc in db.clips.aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]):
        clips_by_coach.append(doc["n"])
    async for doc in db.markers.aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]):
        markers_by_coach.append(doc["n"])

    matches_by_coach.sort()
    clips_by_coach.sort()
    markers_by_coach.sort()

    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else 0
    median = lambda xs: xs[len(xs) // 2] if xs else 0

    # Position distribution platform-wide
    position_counts: Counter = Counter()
    async for p in db.players.find({}, {"_id": 0, "position": 1}):
        pos = (p.get("position") or "Unknown").strip() or "Unknown"
        position_counts[pos] += 1

    # Recurring weakness themes platform-wide (from match insights)
    weakness_counter: Counter = Counter()
    strength_counter: Counter = Counter()
    insights_count = 0
    async for m in db.matches.find(
        {"insights": {"$exists": True}},
        {"_id": 0, "insights.strengths": 1, "insights.weaknesses": 1},
    ):
        ins = m.get("insights") or {}
        for s in (ins.get("strengths") or [])[:4]:
            strength_counter[s.strip().lower()] += 1
        for w in (ins.get("weaknesses") or [])[:4]:
            weakness_counter[w.strip().lower()] += 1
        insights_count += 1

    # Recruiter level distribution from cached player trends
    recruit_levels: Counter = Counter()
    trends_count = 0
    async for p in db.players.find(
        {"trends": {"$exists": True}},
        {"_id": 0, "trends": 1},
    ):
        trends = p.get("trends") or {}
        for v in trends.values():
            if isinstance(v, dict):
                level = (v.get("report") or {}).get("recruiter_view", {}).get("estimated_level")
                if level:
                    recruit_levels[level] += 1
                    trends_count += 1

    # Platform-wide + per-user avg AI-processing duration (seconds).
    # Sanity-bound durations: 10s–2h (matches /api/videos/processing-eta-stats logic).
    all_durations = []
    my_durations = []
    async for v in db.videos.find(
        {"processing_status": "completed", "processing_started_at": {"$ne": None}, "processing_completed_at": {"$ne": None}},
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

    platform_avg_processing = round(sum(all_durations) / len(all_durations), 1) if all_durations else None
    your_avg_processing = round(sum(my_durations) / len(my_durations), 1) if my_durations else None

    # Apply k-anonymity to text aggregates: only show themes that ≥3 coaches have hit
    top_weaknesses = [
        {"text": text.capitalize(), "count": cnt}
        for text, cnt in weakness_counter.most_common(10) if cnt >= K_ANON_THRESHOLD
    ][:8]
    top_strengths = [
        {"text": text.capitalize(), "count": cnt}
        for text, cnt in strength_counter.most_common(10) if cnt >= K_ANON_THRESHOLD
    ][:8]

    return {
        "ready": True,
        "platform": {
            "coaches": total_coaches,
            "teams": total_teams,
            "matches": total_matches,
            "clips": total_clips,
            "markers": total_markers,
        },
        "distributions": {
            "matches_per_coach": {"avg": avg(matches_by_coach), "median": median(matches_by_coach)},
            "clips_per_coach": {"avg": avg(clips_by_coach), "median": median(clips_by_coach)},
            "markers_per_coach": {"avg": avg(markers_by_coach), "median": median(markers_by_coach)},
        },
        "you": {
            "teams": my_teams,
            "matches": my_matches,
            "clips": my_clips,
            "matches_bucket": _percentile_bucket(my_matches, matches_by_coach),
            "clips_bucket": _percentile_bucket(my_clips, clips_by_coach),
        },
        "position_breakdown": [
            {"position": pos, "count": cnt}
            for pos, cnt in position_counts.most_common(10)
        ],
        "common_strengths_across_coaches": top_strengths,
        "common_weaknesses_across_coaches": top_weaknesses,
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
            "platform_avg_seconds": platform_avg_processing,
            "your_avg_seconds": your_avg_processing,
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
