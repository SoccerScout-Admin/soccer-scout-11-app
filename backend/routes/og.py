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
from services.og_card import render_folder_card, render_clip_card

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
    <meta property="og:site_name" content="Soccer Scout" />
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
        f"AI analysis, and clips shared by {coach} on Soccer Scout."
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
        f"shared by {coach} on Soccer Scout."
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
        f"A reel of {n} game-film clip{'s' if n != 1 else ''} curated by {coach} on Soccer Scout."
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
