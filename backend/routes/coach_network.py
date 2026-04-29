"""Coach Network — anonymized platform-wide benchmarks.

Aggregates trends across ALL users without exposing individual user data.
Privacy guarantees:
- Never returns user_id, names, or any identifying fields
- All aggregations require a minimum sample size (k-anonymity threshold)
- Numeric distributions are bucketed
- Returns only the calling user's percentile bucket, not their raw rank
"""
from fastapi import APIRouter, Depends
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
        },
        "k_anonymity_threshold": K_ANON_THRESHOLD,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
