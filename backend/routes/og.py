"""Open Graph share-link prerender endpoints for folders & clips.

Crawlers (WhatsApp, Slack, Twitter, Discord, FB) fetch these HTML pages
to unfurl rich previews. Real browsers JS-redirect to the React SPA route.
"""
import html as html_lib
import json as json_lib
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool
from db import db
from services.og_card import render_folder_card, render_clip_card, render_player_card, render_match_recap_card, render_scout_listing_card
from services.storage import get_object_sync

router = APIRouter()


def _public_base(request: Request) -> str:
    """Return the externally-reachable base URL (handles ingress headers)."""
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}"
    return str(request.base_url).rstrip("/")

def _og_html(title: str, description: str, og_image_url: str, spa_url: str) -> str:
    e_title = html_lib.escape(title)
    e_desc = html_lib.escape(description)
    e_img = html_lib.escape(og_image_url)
    e_spa = html_lib.escape(spa_url)
    spa_js = json_lib.dumps(spa_url)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{e_title}</title>
    <meta name="description" content="{e_desc}" />
    <meta property="og:type" content="article" />
    <meta property="og:title" content="{e_title}" />
    <meta property="og:description" content="{e_desc}" />
    <meta property="og:site_name" content="Soccer Scout 11" />
    <meta property="og:image" content="{e_img}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:type" content="image/png" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{e_title}" />
    <meta name="twitter:description" content="{e_desc}" />
    <meta name="twitter:image" content="{e_img}" />
    <meta http-equiv="refresh" content="0; url={e_spa}" />
    <script>window.location.replace({spa_js});</script>
</head>
<body style="background:#0A0A0A;color:#fff;font-family:system-ui;padding:48px;text-align:center">
    <p>Loading&hellip; <a href="{e_spa}" style="color:#007AFF">Click here</a> if not redirected.</p>
</body>
</html>"""


# ===== Folder OG =====

@router.get("/og/folder/{share_token}")
async def og_folder(share_token: str, request: Request):
    folder = await db.folders.find_one(
        {"share_token": share_token, "is_private": False}, {"_id": 0}
    )
    if not folder:
        return HTMLResponse(
            "<html><body><h1>Link Unavailable</h1></body></html>",
            status_code=404,
        )
    match_count = await db.matches.count_documents(
        {"folder_id": folder["id"], "user_id": folder["user_id"]}
    )
    owner = await db.users.find_one({"id": folder["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "Coach")

    title = f"{folder['name']} — Match Film"
    description = (
        f"{match_count} {'match' if match_count == 1 else 'matches'} of game film, "
        f"AI analysis, and clips shared by {coach} on Soccer Scout 11."
    )
    spa_url = f"/shared/{share_token}"
    image_url = f"{_public_base(request)}/api/og/folder/{share_token}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/folder/{share_token}/image.png")
async def og_folder_image(share_token: str):
    folder = await db.folders.find_one(
        {"share_token": share_token, "is_private": False}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Not found")
    matches = await db.matches.find(
        {"folder_id": folder["id"], "user_id": folder["user_id"]},
        {"_id": 0, "team_home": 1, "team_away": 1, "date": 1},
    ).sort("date", -1).to_list(50)
    owner = await db.users.find_one({"id": folder["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "")
    match_labels = [
        f"{m.get('team_home', 'Home')} vs {m.get('team_away', 'Away')}"
        for m in matches[:3]
    ]
    png = await run_in_threadpool(
        render_folder_card,
        folder["name"],
        coach,
        len(matches),
        match_labels,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ===== Clip OG =====

@router.get("/og/clip/{share_token}")
async def og_clip(share_token: str, request: Request):
    clip = await db.clips.find_one({"share_token": share_token}, {"_id": 0})
    if not clip:
        return HTMLResponse(
            "<html><body><h1>Link Unavailable</h1></body></html>",
            status_code=404,
        )
    match = await db.matches.find_one(
        {"id": clip.get("match_id")},
        {"_id": 0, "team_home": 1, "team_away": 1},
    ) or {}
    owner = await db.users.find_one({"id": clip["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "Coach")

    match_label = ""
    if match.get("team_home") and match.get("team_away"):
        match_label = f"{match['team_home']} vs {match['team_away']}"

    duration = max(0, (clip.get("end_time") or 0) - (clip.get("start_time") or 0))
    mins = int(duration // 60)
    secs = int(duration % 60)
    title_parts = [clip.get("title") or "Video Clip"]
    if match_label:
        title_parts.append(match_label)
    title = " — ".join(title_parts)
    description = (
        f"{mins}:{secs:02d} clip of {clip.get('clip_type', 'highlight')} "
        f"shared by {coach} on Soccer Scout 11."
    )
    spa_url = f"/clip/{share_token}"
    image_url = f"{_public_base(request)}/api/og/clip/{share_token}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/clip/{share_token}/image.png")
async def og_clip_image(share_token: str):
    clip = await db.clips.find_one({"share_token": share_token}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Not found")
    match = await db.matches.find_one(
        {"id": clip.get("match_id")},
        {"_id": 0, "team_home": 1, "team_away": 1},
    ) or {}
    owner = await db.users.find_one({"id": clip["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "")

    match_label = ""
    if match.get("team_home") and match.get("team_away"):
        match_label = f"{match['team_home']} vs {match['team_away']}"

    duration = max(0, (clip.get("end_time") or 0) - (clip.get("start_time") or 0))

    png = await run_in_threadpool(
        render_clip_card,
        clip.get("title") or "Video Clip",
        match_label,
        coach,
        duration,
        clip.get("clip_type", "highlight"),
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )



# ===== Match Recap OG =====

@router.get("/og/match-recap/{share_token}")
async def og_match_recap(share_token: str, request: Request):
    """HTML page with OG meta tags so WhatsApp/Slack/Twitter unfurl the recap card."""
    match = await db.matches.find_one(
        {"manual_result.recap_share_token": share_token},
        {"_id": 0},
    )
    if not match:
        return HTMLResponse(
            "<html><body><h1>Recap Unavailable</h1></body></html>",
            status_code=404,
        )
    mr = match.get("manual_result") or {}
    insights = match.get("insights") or {}
    owner = await db.users.find_one({"id": match["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "Coach")
    _ = coach  # reserved for future subtitle use in the unfurl HTML
    title = f"{match['team_home']} {mr.get('home_score', 0)}-{mr.get('away_score', 0)} {match['team_away']}"
    if match.get("competition"):
        title += f" — {match['competition']}"
    description = (insights.get("summary") or "Final whistle. AI match recap.")[:280]
    spa_url = f"/match-recap/{share_token}"
    image_url = f"{_public_base(request)}/api/og/match-recap/{share_token}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/match-recap/{share_token}/image.png")
async def og_match_recap_image(share_token: str):
    match = await db.matches.find_one(
        {"manual_result.recap_share_token": share_token},
        {"_id": 0},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Not found")
    mr = match.get("manual_result") or {}
    insights = match.get("insights") or {}
    owner = await db.users.find_one({"id": match["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "")

    png = await run_in_threadpool(
        render_match_recap_card,
        match["team_home"],
        match["team_away"],
        mr.get("home_score", 0),
        mr.get("away_score", 0),
        match.get("competition") or "",
        coach,
        insights.get("summary") or "",
        mr.get("outcome", "D"),
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/match-recap/public/{share_token}")
async def get_public_match_recap(share_token: str):
    """JSON fetch endpoint for the React SPA route /match-recap/{token}."""
    match = await db.matches.find_one(
        {"manual_result.recap_share_token": share_token},
        {"_id": 0},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Recap not found or sharing was revoked")
    mr = match.get("manual_result") or {}
    insights = match.get("insights") or {}
    owner = await db.users.find_one({"id": match["user_id"]}, {"_id": 0, "name": 1})
    return {
        "team_home": match["team_home"],
        "team_away": match["team_away"],
        "home_score": mr.get("home_score", 0),
        "away_score": mr.get("away_score", 0),
        "outcome": mr.get("outcome", "D"),
        "date": match.get("date"),
        "competition": match.get("competition") or "",
        "coach_name": (owner or {}).get("name", ""),
        "summary": insights.get("summary") or "",
        "key_events": mr.get("key_events", []),
        "finished_at": mr.get("finished_at"),
    }



# ===== Clip Collection OG (batch share) =====

@router.get("/og/clip-collection/{share_token}")
async def og_clip_collection(share_token: str, request: Request):
    coll = await db.clip_collections.find_one({"share_token": share_token}, {"_id": 0})
    if not coll:
        return HTMLResponse(
            "<html><body><h1>Link Unavailable</h1></body></html>",
            status_code=404,
        )
    owner = await db.users.find_one(
        {"id": coll["user_id"]}, {"_id": 0, "name": 1}
    )
    coach = (owner or {}).get("name", "Coach")
    n = len(coll.get("clip_ids") or [])

    title = coll.get("title") or f"{n} Clips"
    description = (
        f"A reel of {n} game-film clip{'s' if n != 1 else ''} curated by {coach} on Soccer Scout 11."
    )
    spa_url = f"/clips/{share_token}"
    image_url = f"{_public_base(request)}/api/og/clip-collection/{share_token}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/clip-collection/{share_token}/image.png")
async def og_clip_collection_image(share_token: str):
    coll = await db.clip_collections.find_one({"share_token": share_token}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Not found")

    clips = await db.clips.find(
        {"id": {"$in": coll.get("clip_ids") or []}, "user_id": coll["user_id"]},
        {"_id": 0, "title": 1, "clip_type": 1, "start_time": 1, "end_time": 1},
    ).to_list(200)

    owner = await db.users.find_one(
        {"id": coll["user_id"]}, {"_id": 0, "name": 1}
    )
    coach = (owner or {}).get("name", "")

    # Reuse render_folder_card with type-prefixed labels for now.
    labels = []
    for c in clips[:3]:
        labels.append(c.get("title") or c.get("clip_type", "Clip").upper())

    png = await run_in_threadpool(
        render_folder_card,
        coll.get("title") or f"{len(clips)} Clips",
        coach,
        len(clips),
        labels,
        "CLIP REEL",
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )



# ===== Player OG (public dossier) =====

@router.get("/og/player/{share_token}")
async def og_player(share_token: str, request: Request):
    player = await db.players.find_one({"share_token": share_token}, {"_id": 0})
    if not player:
        return HTMLResponse(
            "<html><body><h1>Link Unavailable</h1></body></html>",
            status_code=404,
        )
    owner = await db.users.find_one({"id": player["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "Coach")

    name = player.get("name") or "Player"
    number = player.get("number")
    position = player.get("position") or ""

    title_parts = []
    if number is not None:
        title_parts.append(f"#{number}")
    title_parts.append(name)
    title = " ".join(title_parts)
    if position:
        title = f"{title} — {position}"

    clip_count = await db.clips.count_documents(
        {"player_ids": player["id"], "user_id": player["user_id"]}
    )
    description = (
        f"Player dossier for {name}. {clip_count} clip{'s' if clip_count != 1 else ''} "
        f"on Soccer Scout 11, shared by {coach}."
    )

    spa_url = f"/shared-player/{share_token}"
    image_url = f"{_public_base(request)}/api/og/player/{share_token}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/player/{share_token}/image.png")
async def og_player_image(share_token: str):
    player = await db.players.find_one(
        {"share_token": share_token}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Not found")

    user_id = player["user_id"]

    # Stats by clip type
    clips = await db.clips.find(
        {"player_ids": player["id"], "user_id": user_id},
        {"_id": 0, "clip_type": 1},
    ).to_list(500)
    stats: dict[str, int] = {}
    for c in clips:
        t = (c.get("clip_type") or "highlight").lower()
        stats[t] = stats.get(t, 0) + 1

    # Teams summary: "U17 + U19 (2025/26)"
    team_ids = player.get("team_ids") or []
    teams = []
    if team_ids:
        teams = await db.teams.find(
            {"id": {"$in": team_ids}, "user_id": user_id},
            {"_id": 0, "name": 1, "season": 1},
        ).to_list(50)
    seasons = sorted({t["season"] for t in teams}, reverse=True)
    teams_summary = ""
    if teams:
        teams_summary = f"{len(teams)} team{'s' if len(teams) != 1 else ''}"
        if seasons:
            teams_summary += f" • {seasons[0]}"

    # Profile pic bytes
    profile_pic_bytes = None
    if player.get("profile_pic_path"):
        try:
            profile_pic_bytes, _ = await run_in_threadpool(
                get_object_sync, player["profile_pic_path"]
            )
        except Exception:
            pass

    owner = await db.users.find_one({"id": user_id}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "")

    png = await run_in_threadpool(
        render_player_card,
        player.get("name") or "Player",
        player.get("number"),
        player.get("position") or "",
        teams_summary,
        stats,
        coach,
        profile_pic_bytes,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )



# ===== Club OG (public club home page) =====

@router.get("/og/club/{share_token}")
async def og_club(share_token: str, request: Request):
    club = await db.clubs.find_one({"share_token": share_token}, {"_id": 0})
    if not club:
        return HTMLResponse("<html><body><h1>Link Unavailable</h1></body></html>", status_code=404)
    team_count = await db.teams.count_documents(
        {"club": club["id"], "user_id": club["user_id"]}
    )
    owner = await db.users.find_one({"id": club["user_id"]}, {"_id": 0, "name": 1})
    coach = (owner or {}).get("name", "Coach")
    title = club["name"]
    description = (
        f"{team_count} team{'s' if team_count != 1 else ''} across the seasons. "
        f"Public club home shared by {coach} on Soccer Scout 11."
    )
    spa_url = f"/shared-club/{share_token}"
    image_url = f"{_public_base(request)}/api/og/club/{share_token}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/club/{share_token}/image.png")
async def og_club_image(share_token: str):
    from services.og_card import render_team_card  # club uses the team-card layout
    club = await db.clubs.find_one({"share_token": share_token}, {"_id": 0})
    if not club:
        raise HTTPException(status_code=404, detail="Not found")

    team_count = await db.teams.count_documents(
        {"club": club["id"], "user_id": club["user_id"]}
    )
    player_count = await db.players.count_documents(
        {"user_id": club["user_id"]}
    )

    logo_bytes = None
    if club.get("logo_path"):
        try:
            logo_bytes, _ = await run_in_threadpool(get_object_sync, club["logo_path"])
        except Exception:
            pass

    # Reuse team-card layout: name, "club" → label as season slot, etc.
    png = await run_in_threadpool(
        render_team_card,
        club["name"],
        f"{team_count} Team{'s' if team_count != 1 else ''}",
        "",
        player_count,
        logo_bytes,
        [],
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )



# ---------- Scout listings ----------

@router.get("/og/scout-listing/{listing_id}")
async def og_scout_listing(listing_id: str, request: Request):
    """HTML page with OG meta tags so social media unfurls the listing card."""
    listing = await db.scout_listings.find_one({"id": listing_id}, {"_id": 0})
    if not listing:
        return HTMLResponse(
            "<html><body><h1>Listing not found</h1></body></html>",
            status_code=404,
        )
    title = f"{listing['school_name']} — Recruiting Listing"
    if listing.get("level"):
        title += f" · {listing['level']}"
    description = (listing.get("description") or "")[:280]
    spa_url = f"/scouts/{listing_id}"
    image_url = f"{_public_base(request)}/api/og/scout-listing/{listing_id}/image.png"
    return HTMLResponse(_og_html(title, description, image_url, spa_url))


@router.get("/og/scout-listing/{listing_id}/image.png")
async def og_scout_listing_image(listing_id: str):
    listing = await db.scout_listings.find_one({"id": listing_id}, {"_id": 0})
    if not listing:
        raise HTTPException(status_code=404, detail="Not found")

    logo_bytes = None
    if listing.get("school_logo_path"):
        try:
            logo_bytes, _ct = await run_in_threadpool(get_object_sync, listing["school_logo_path"])
        except Exception:
            logo_bytes = None

    png = await run_in_threadpool(
        render_scout_listing_card,
        listing.get("school_name", ""),
        listing.get("level", ""),
        listing.get("region", ""),
        listing.get("positions") or [],
        listing.get("grad_years") or [],
        listing.get("description", ""),
        logo_bytes,
        bool(listing.get("verified")),
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
