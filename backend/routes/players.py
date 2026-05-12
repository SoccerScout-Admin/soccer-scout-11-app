"""Player management routes with multi-team support (max 2 teams per season)."""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from typing import Optional, List
from pydantic import BaseModel
import uuid
import csv
import io
from datetime import datetime, timezone
from starlette.concurrency import run_in_threadpool
from db import db, APP_NAME
from models import Player
from routes.auth import get_current_user
from services.storage import put_object_sync, get_object_sync

router = APIRouter()

MAX_TEAMS_PER_SEASON = 2


class PlayerCreate(BaseModel):
    match_id: Optional[str] = None
    # Accept either single team_id (legacy) or team_ids array. Both end up in team_ids.
    team_id: Optional[str] = None
    team_ids: Optional[List[str]] = None
    name: str
    number: Optional[int] = None
    position: Optional[str] = None
    team: Optional[str] = None
    birth_year: Optional[int] = None
    current_grade: Optional[str] = None


class PlayerUpdate(BaseModel):
    """iter57: PATCH body. All fields optional — only provided ones are
    applied. Switched from query params → JSON body so the schema can grow
    without endpoint signature explosion."""
    name: Optional[str] = None
    number: Optional[int] = None
    position: Optional[str] = None
    team: Optional[str] = None
    match_id: Optional[str] = None
    birth_year: Optional[int] = None
    current_grade: Optional[str] = None


class CsvImport(BaseModel):
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    csv_data: str
    team: Optional[str] = None


async def _enforce_season_cap(user_id: str, player_id: Optional[str], team_ids: List[str]) -> None:
    """Ensure no season has more than MAX_TEAMS_PER_SEASON entries for this player."""
    if not team_ids:
        return
    teams = await db.teams.find(
        {"id": {"$in": team_ids}, "user_id": user_id},
        {"_id": 0, "id": 1, "season": 1, "name": 1},
    ).to_list(50)

    by_season: dict[str, list[str]] = {}
    for t in teams:
        by_season.setdefault(t["season"], []).append(t["name"])

    for season, names in by_season.items():
        if len(names) > MAX_TEAMS_PER_SEASON:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Player can be on at most {MAX_TEAMS_PER_SEASON} teams in season "
                    f"{season} (got {len(names)}: {', '.join(names)})."
                ),
            )


def _strip_storage_fields(p: dict) -> dict:
    """Remove internal storage paths before returning to clients."""
    out = {k: v for k, v in p.items() if k != "profile_pic_path"}
    return out


@router.post("/players")
async def create_player(input: PlayerCreate, current_user: dict = Depends(get_current_user)):
    team_ids: List[str] = []
    if input.team_ids:
        team_ids = list(input.team_ids)
    elif input.team_id:
        team_ids = [input.team_id]

    await _enforce_season_cap(current_user["id"], None, team_ids)

    player = Player(
        user_id=current_user["id"],
        match_id=input.match_id,
        team_ids=team_ids,
        name=input.name,
        number=input.number,
        position=input.position,
        team=input.team,
        birth_year=input.birth_year,
        current_grade=input.current_grade,
    )
    await db.players.insert_one(player.model_dump())
    return player.model_dump()


@router.get("/players/match/{match_id}")
async def get_match_players(match_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find(
        {"match_id": match_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(200)
    return [_strip_storage_fields(p) for p in players]


@router.get("/players/team/{team_id}")
async def get_team_players(team_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find(
        {"team_ids": team_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(200)
    return [_strip_storage_fields(p) for p in players]


@router.delete("/players/{player_id}")
async def delete_player(player_id: str, current_user: dict = Depends(get_current_user)):
    """Hard-delete a player record entirely."""
    result = await db.players.delete_one({"id": player_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"status": "deleted"}


@router.get("/players/my-shared")
async def my_shared_players(current_user: dict = Depends(get_current_user)):
    """Players I own that have a public dossier share_token enabled.

    Used by the Express Interest modal so coaches can attach an existing
    public dossier to their outreach without leaving the page.
    """
    rows = await db.players.find(
        {
            "user_id": current_user["id"],
            "share_token": {"$exists": True, "$ne": None},
        },
        {"_id": 0, "id": 1, "name": 1, "number": 1, "position": 1, "share_token": 1},
    ).sort("name", 1).to_list(200)
    return rows


@router.post("/players/{player_id}/teams/{team_id}")
async def add_player_to_team(
    player_id: str, team_id: str, current_user: dict = Depends(get_current_user)
):
    """Add an existing player to an additional team (respects 2-per-season cap)."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    team = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    current_teams = list(player.get("team_ids") or [])
    if team_id in current_teams:
        return {"status": "already-on-team", "team_ids": current_teams}

    proposed = current_teams + [team_id]
    await _enforce_season_cap(current_user["id"], player_id, proposed)

    await db.players.update_one(
        {"id": player_id}, {"$set": {"team_ids": proposed}}
    )
    return {"status": "added", "team_ids": proposed}


@router.delete("/players/{player_id}/teams/{team_id}")
async def remove_player_from_team(
    player_id: str, team_id: str, current_user: dict = Depends(get_current_user)
):
    """Remove a player from a single team (player record stays if other teams remain)."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    current_teams = list(player.get("team_ids") or [])
    if team_id not in current_teams:
        return {"status": "not-on-team"}
    new_teams = [t for t in current_teams if t != team_id]
    await db.players.update_one(
        {"id": player_id}, {"$set": {"team_ids": new_teams}}
    )
    return {"status": "removed", "team_ids": new_teams}


@router.post("/players/import-csv")
async def import_csv(input: CsvImport, current_user: dict = Depends(get_current_user)):
    """Import players from CSV data. Columns: name,number,position"""
    reader = csv.DictReader(io.StringIO(input.csv_data))
    imported = 0
    target_team_ids = [input.team_id] if input.team_id else []
    for row in reader:
        name = row.get("name", "").strip()
        if not name:
            continue
        number = None
        try:
            number = int(row.get("number", "").strip())
        except (ValueError, AttributeError):
            pass
        position = row.get("position", "").strip() or None
        player = Player(
            user_id=current_user["id"],
            match_id=input.match_id,
            team_ids=list(target_team_ids),
            name=name,
            number=number,
            position=position,
            team=input.team,
        )
        await db.players.insert_one(player.model_dump())
        imported += 1
    return {"imported": imported}


# ---------- Roster file import (CSV) ----------

# Accept a wide range of column header spellings — coaches paste from Excel,
# Google Sheets, Hudl exports, TeamSnap exports, or print rosters where
# conventions vary wildly.
_HEADER_ALIASES = {
    "name": {"name", "player", "player name", "full name", "fullname", "athlete"},
    # iter59: Hudl/TeamSnap exports split into First Name + Last Name.
    "first_name": {"first name", "firstname", "first", "given name"},
    "last_name": {"last name", "lastname", "last", "family name", "surname"},
    "number": {"number", "no", "no.", "#", "jersey", "jersey number", "shirt", "shirt no", "uniform"},
    "position": {"position", "pos", "pos.", "primary position", "primary pos"},
    # iter58: roster demographics for HS/club/college rosters
    "birth_year": {
        "birth year", "birthyear", "year of birth", "yob", "born", "birth",
        # iter59: Hudl/TeamSnap full-date columns — our regex extracts the year
        "date of birth", "dob", "birthdate", "birth date",
    },
    "current_grade": {"grade", "current grade", "class", "year", "school year", "level"},
    # iter59: Hudl exports a "Grad Year" — we'll derive current_grade from it.
    "grad_year": {"grad year", "graduation year", "class of", "graduating class"},
    # iter59: TeamSnap exports a "Member Type" — we skip rows that aren't players.
    "member_type": {"member type", "role", "type"},
}

# iter59: Map grad_year offset → current_grade label. Computed as
# (grad_year - current_school_year_end), with grad year > current year being
# underclassmen. Symmetric with the frontend `classOfLabel` derivation.
_GRAD_TO_GRADE = {
    -1: "Graduate / Post-Grad",
    0: "12th (Senior)",
    1: "11th (Junior)",
    2: "10th (Sophomore)",
    3: "9th (Freshman)",
    4: "8th",
    5: "7th",
    6: "6th",
}


def _grade_from_grad_year(grad_year: int) -> Optional[str]:
    """Convert a 4-digit grad year (e.g. 2027) → grade label like '11th (Junior)'.

    Uses Aug–Jul school-year semantics so a Feb 2026 import treats grad year
    2026 as the current senior class.
    """
    now = datetime.now(timezone.utc)
    school_year_end = now.year + 1 if now.month >= 7 else now.year
    offset = grad_year - school_year_end
    return _GRAD_TO_GRADE.get(offset)


def _normalize_header(h: str) -> str:
    return (h or "").strip().lower().replace("_", " ")


def _resolve_columns(fieldnames: list[str]) -> dict[str, Optional[str]]:
    """Map our canonical fields → the actual CSV header that was used."""
    resolved: dict[str, Optional[str]] = {k: None for k in _HEADER_ALIASES}
    for canonical, aliases in _HEADER_ALIASES.items():
        for actual in fieldnames or []:
            if _normalize_header(actual) in aliases:
                resolved[canonical] = actual
                break
    return resolved


@router.get("/players/import-template.csv")
async def download_roster_template():
    """A starter CSV with the canonical headers + 3 example rows.

    Coaches can download this, fill it in Excel/Google Sheets, save as CSV,
    and upload back. Public — no auth needed because it's a static template.

    iter58: birth_year and current_grade columns added. Both are optional —
    leaving them blank still imports the row. Existing 3-column rosters that
    omit them keep working unchanged.
    """
    from fastapi.responses import Response
    body = (
        "name,number,position,birth_year,current_grade\n"
        "Jane Doe,9,ST,2008,11th (Junior)\n"
        "Maria Lopez,4,CB,2007,12th (Senior)\n"
        "Sam Lee,10,CM,2009,10th (Sophomore)\n"
    )
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="roster-template.csv"'},
    )


@router.post("/teams/{team_id}/players/import")
async def import_team_roster(
    team_id: str,
    file: UploadFile = File(...),
    dry_run: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Bulk-import players to a team from a CSV file.

    Returns `{imported, skipped, errors: [{row, reason}], parsed: [...]}`.
    With `dry_run=true` we report what *would* happen without writing anything,
    so the UI can show a preview/confirm flow.

    Accepts ~tolerant headers (case-insensitive, alias-aware). Empty-name
    rows are skipped silently. Bad jersey numbers are reported but the row
    is still imported with `number=null`. Numbers must fit 0..999 to fit a
    reasonable jersey range.
    """
    team = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1, "name": 1}
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    if len(raw) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 1MB).")

    try:
        # Try utf-8-sig first to strip Excel's BOM, fall back to latin-1.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not decode file: {exc}")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    columns = _resolve_columns(fieldnames)
    # iter59: accept either a single 'name' column OR split first+last from
    # Hudl/TeamSnap exports.
    has_split_name = columns["first_name"] and columns["last_name"]
    if not columns["name"] and not has_split_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not find a 'name' column. Accepted headers: "
                "name, player, player name, full name, athlete, "
                "or split First Name + Last Name (Hudl/TeamSnap format)."
            ),
        )

    parsed: list[dict] = []
    errors: list[dict] = []
    skipped = 0

    for idx, row in enumerate(reader, start=2):  # row 1 is the header
        # iter59: TeamSnap exports include coaches/managers — skip non-player rows.
        if columns["member_type"]:
            member = (row.get(columns["member_type"]) or "").strip().lower()
            if member and member not in {"player", "athlete"}:
                skipped += 1
                continue

        # iter59: resolve name from either single column or first+last split.
        if columns["name"]:
            raw_name = (row.get(columns["name"]) or "").strip()
        else:
            first = (row.get(columns["first_name"]) or "").strip()
            last = (row.get(columns["last_name"]) or "").strip()
            raw_name = f"{first} {last}".strip()

        if not raw_name:
            skipped += 1
            continue

        # Number — optional. We want clear feedback if the user wrote "9.5" or
        # "GK" in the number column.
        num_value: Optional[int] = None
        if columns["number"]:
            raw_num = (row.get(columns["number"]) or "").strip()
            if raw_num:
                try:
                    num_value = int(raw_num)
                    if num_value < 0 or num_value > 999:
                        raise ValueError("out of range")
                except (ValueError, TypeError):
                    errors.append({
                        "row": idx,
                        "reason": f"Invalid jersey number '{raw_num}' for {raw_name} — imported with no number.",
                    })
                    num_value = None

        position = None
        if columns["position"]:
            position = (row.get(columns["position"]) or "").strip() or None

        # iter58 — birth_year is optional. Be lenient: accept '2008', '08',
        # '2008-05-12' (extract year), or empty.
        birth_year: Optional[int] = None
        if columns["birth_year"]:
            raw_by = (row.get(columns["birth_year"]) or "").strip()
            if raw_by:
                # If the user wrote a full date, grab the first 4-digit run
                import re as _re
                m = _re.search(r"\d{4}", raw_by)
                if m:
                    try:
                        candidate = int(m.group())
                        # Sanity: only accept plausible roster ages (5–30 years old)
                        current_year = datetime.now(timezone.utc).year
                        if current_year - 30 <= candidate <= current_year - 5:
                            birth_year = candidate
                        else:
                            errors.append({
                                "row": idx,
                                "reason": f"Birth year '{raw_by}' out of range for {raw_name} — imported with no birth year.",
                            })
                    except ValueError:
                        pass
                elif raw_by:
                    errors.append({
                        "row": idx,
                        "reason": f"Could not parse birth year '{raw_by}' for {raw_name} — imported with no birth year.",
                    })

        current_grade: Optional[str] = None
        if columns["current_grade"]:
            current_grade = (row.get(columns["current_grade"]) or "").strip() or None
        # iter59: Hudl exports use "Grad Year" instead — derive the grade label
        # if a direct one wasn't provided.
        if not current_grade and columns["grad_year"]:
            raw_gy = (row.get(columns["grad_year"]) or "").strip()
            if raw_gy:
                import re as _re2
                m_gy = _re2.search(r"\d{4}", raw_gy)
                if m_gy:
                    try:
                        gy = int(m_gy.group())
                        current_grade = _grade_from_grad_year(gy)
                        if current_grade is None:
                            errors.append({
                                "row": idx,
                                "reason": f"Grad year '{raw_gy}' for {raw_name} is outside our HS/college range — grade not derived.",
                            })
                    except ValueError:
                        pass

        parsed.append({
            "row": idx,
            "name": raw_name,
            "number": num_value,
            "position": position,
            "birth_year": birth_year,
            "current_grade": current_grade,
        })

    if dry_run:
        return {
            "dry_run": True,
            "imported": 0,
            "skipped": skipped,
            "errors": errors,
            "parsed": parsed,
            "team_id": team_id,
            "team_name": team["name"],
        }

    if not parsed:
        return {
            "dry_run": False,
            "imported": 0,
            "skipped": skipped,
            "errors": errors,
            "parsed": [],
            "team_id": team_id,
            "team_name": team["name"],
        }

    # Bulk insert — validate season cap once on the team itself.
    await _enforce_season_cap(current_user["id"], None, [team_id])
    docs = []
    for item in parsed:
        player = Player(
            user_id=current_user["id"],
            match_id=None,
            team_ids=[team_id],
            name=item["name"],
            number=item["number"],
            position=item["position"],
            team=team["name"],
            birth_year=item.get("birth_year"),
            current_grade=item.get("current_grade"),
        )
        docs.append(player.model_dump())
    if docs:
        await db.players.insert_many(docs)

    return {
        "dry_run": False,
        "imported": len(docs),
        "skipped": skipped,
        "errors": errors,
        "parsed": parsed,
        "team_id": team_id,
        "team_name": team["name"],
    }


@router.post("/players/{player_id}/profile-pic")
async def upload_profile_pic(
    player_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload a player's profile picture"""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")

    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    storage_path = f"{APP_NAME}/players/{current_user['id']}/{player_id}.{ext}"

    await run_in_threadpool(put_object_sync, storage_path, data, file.content_type)

    pic_url = f"/api/players/{player_id}/profile-pic/view"
    await db.players.update_one(
        {"id": player_id},
        {"$set": {"profile_pic_url": pic_url, "profile_pic_path": storage_path}},
    )
    return {"url": pic_url}


@router.get("/players/{player_id}/profile-pic/view")
async def view_profile_pic(player_id: str):
    """Serve a player's profile picture (public)"""
    player = await db.players.find_one(
        {"id": player_id}, {"_id": 0, "profile_pic_path": 1}
    )
    if not player or not player.get("profile_pic_path"):
        raise HTTPException(status_code=404, detail="No profile picture")
    try:
        data, content_type = await run_in_threadpool(
            get_object_sync, player["profile_pic_path"]
        )
        from fastapi.responses import Response
        return Response(content=data, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@router.patch("/players/{player_id}")
async def update_player(
    player_id: str,
    update: PlayerUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Edit an existing player. JSON body — only provided fields are applied.

    iter57: switched from query params to a JSON body so the schema can grow
    cleanly (birth_year, current_grade added). Frontend sends a partial
    object; we filter to non-None values and $set them."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    payload = update.model_dump(exclude_none=True)
    if payload:
        await db.players.update_one({"id": player_id}, {"$set": payload})
    return {"status": "updated", "fields_updated": list(payload.keys())}


# ===== Roster discovery for "Add Existing Player" flow =====

@router.get("/teams/{team_id}/eligible-players")
async def eligible_players_for_team(
    team_id: str, current_user: dict = Depends(get_current_user)
):
    """Players who are NOT yet on this team, but are on another team in the same
    season. They're eligible to be added (subject to the 2-per-season cap)."""
    team = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    same_season_teams = await db.teams.find(
        {"user_id": current_user["id"], "season": team["season"], "id": {"$ne": team_id}},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(100)
    other_team_ids = [t["id"] for t in same_season_teams]
    if not other_team_ids:
        return []

    candidates = await db.players.find(
        {"user_id": current_user["id"], "team_ids": {"$in": other_team_ids}},
        {"_id": 0, "profile_pic_path": 0},
    ).to_list(500)

    team_name_by_id = {t["id"]: t["name"] for t in same_season_teams}
    out = []
    for p in candidates:
        p_team_ids = list(p.get("team_ids") or [])
        if team_id in p_team_ids:
            continue  # already on the target team
        # Annotate which other teams this player is on (for UI context)
        other_names = [
            team_name_by_id[tid] for tid in p_team_ids if tid in team_name_by_id
        ]
        # Block if at the cap (2) - they would exceed if we added them
        at_cap = len(p_team_ids) >= MAX_TEAMS_PER_SEASON
        out.append({**p, "other_team_names": other_names, "at_cap": at_cap})
    return out


# ===== Promote roster to next season =====

class PromoteRosterRequest(BaseModel):
    new_season: str
    new_team_name: Optional[str] = None  # default: same as source team
    keep_old: bool = True  # default: also keep on the old team


@router.post("/teams/{team_id}/promote")
async def promote_team_to_next_season(
    team_id: str,
    body: PromoteRosterRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new team for next season in the same club and copy the entire
    roster's identity to it. Each player gets the new team appended to their
    `team_ids` so they appear on both rosters by default."""
    src = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not src:
        raise HTTPException(status_code=404, detail="Source team not found")
    if not body.new_season.strip():
        raise HTTPException(status_code=400, detail="new_season is required")
    if body.new_season == src["season"]:
        raise HTTPException(
            status_code=400, detail="new_season must differ from the current season"
        )

    new_team_id = str(uuid.uuid4())
    new_team = {
        "id": new_team_id,
        "user_id": current_user["id"],
        "name": body.new_team_name or src["name"],
        "club": src.get("club"),
        "season": body.new_season.strip(),
        "logo_url": None,
        "share_token": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.teams.insert_one(new_team)

    # Copy players: append new_team_id to each player's team_ids.
    # If keep_old=False, also remove the old team_id.
    roster = await db.players.find(
        {"team_ids": team_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(500)

    promoted = 0
    for p in roster:
        new_ids = list(p.get("team_ids") or [])
        if not body.keep_old and team_id in new_ids:
            new_ids = [t for t in new_ids if t != team_id]
        if new_team_id not in new_ids:
            new_ids.append(new_team_id)
        await db.players.update_one(
            {"id": p["id"]}, {"$set": {"team_ids": new_ids}}
        )
        promoted += 1

    return {
        "status": "promoted",
        "new_team_id": new_team_id,
        "promoted_count": promoted,
        "new_team": {k: v for k, v in new_team.items() if k != "_id"},
    }
