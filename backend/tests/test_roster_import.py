"""Roster CSV import — POST /api/teams/{id}/players/import.

Surfaces under test:
- Auth required
- 404 for unknown / cross-user team
- Empty file -> 400
- Missing 'name' column -> 400 with helpful message
- File too large -> 413
- Header aliases (Player Name, Jersey Number, Pos.) work
- Bad jersey numbers reported as warnings, row still imported with number=null
- Empty rows skipped silently
- dry_run=true returns parsed payload without writing
- Actual import inserts rows with team_ids = [team_id]
- Bulk insert + season cap enforcement
"""
from __future__ import annotations

import io
import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


@pytest.fixture(scope="module")
def coach_user():
    email = f"importtest-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "ImpPass123", "name": "Import Coach", "role": "coach"},
    )
    if r.status_code != 200:
        pytest.skip(f"Could not register coach: {r.status_code} {r.text}")
    data = r.json()
    return {
        "email": email,
        "id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['token']}"},
    }


@pytest.fixture(scope="module")
def team(coach_user):
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": f"ImportTest-{uuid.uuid4().hex[:6]}", "season": "2026"},
        headers={**coach_user["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    team_data = r.json()
    yield team_data
    # cleanup
    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team_data["id"]})
        await db.teams.delete_one({"id": team_data["id"]})
        await db.users.delete_one({"email": coach_user["email"]})
    _run_async(go())


def _post_csv(team_id, headers, content: str, dry_run=False):
    files = {"file": ("roster.csv", io.BytesIO(content.encode("utf-8")), "text/csv")}
    params = {"dry_run": "true"} if dry_run else None
    return requests.post(
        f"{BASE_URL}/api/teams/{team_id}/players/import",
        headers=headers, files=files, params=params,
    )


# ---------- auth + ownership ----------

def test_import_requires_auth(team):
    r = _post_csv(team["id"], {}, "name\nJohn")
    assert r.status_code in (401, 403)


def test_import_unknown_team_returns_404(coach_user):
    r = _post_csv(str(uuid.uuid4()), coach_user["headers"], "name\nJohn")
    assert r.status_code == 404


# ---------- file validation ----------

def test_import_empty_file_returns_400(team, coach_user):
    r = _post_csv(team["id"], coach_user["headers"], "")
    assert r.status_code == 400, r.text
    assert "empty" in r.json()["detail"].lower()


def test_import_missing_name_column_returns_400(team, coach_user):
    r = _post_csv(team["id"], coach_user["headers"], "foo,bar\n1,2\n")
    assert r.status_code == 400, r.text
    assert "name" in r.json()["detail"].lower()


def test_import_oversized_file_returns_413(team, coach_user):
    big = "name\n" + ("X" * 200 + "\n") * 6000  # >1MB
    r = _post_csv(team["id"], coach_user["headers"], big)
    assert r.status_code == 413, r.text


# ---------- header alias tolerance ----------

def test_import_accepts_header_aliases(team, coach_user):
    csv_text = "Player Name,Jersey Number,Pos.\nJane Doe,9,ST\nMaria Lopez,4,CB\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2
    # Cleanup so subsequent tests start clean
    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


# ---------- dry-run vs real import ----------

def test_dry_run_does_not_write(team, coach_user):
    csv_text = "name,number,position\nDry Doe,7,ST\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text, dry_run=True)
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["imported"] == 0
    assert len(body["parsed"]) == 1
    assert body["parsed"][0]["name"] == "Dry Doe"

    # Confirm DB is empty
    async def go():
        from db import db
        return await db.players.count_documents({"team_ids": team["id"]})
    assert _run_async(go()) == 0


def test_actual_import_writes_rows(team, coach_user):
    csv_text = "name,number,position\nA Smith,1,GK\nB Jones,2,FB\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert body["dry_run"] is False
    # Confirm via /api/players/team
    r = requests.get(f"{BASE_URL}/api/players/team/{team['id']}", headers=coach_user["headers"])
    names = sorted(p["name"] for p in r.json())
    assert names == ["A Smith", "B Jones"]

    # Cleanup
    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


# ---------- error reporting ----------

def test_bad_number_reports_warning_but_imports_row(team, coach_user):
    csv_text = "name,number,position\nGood Player,9,ST\nBad Number,Not A Number,GK\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 3
    assert "Not A Number" in body["errors"][0]["reason"]
    # The row still got imported but with number=null
    rows = [p for p in body["parsed"] if p["name"] == "Bad Number"]
    assert rows[0]["number"] is None

    # Cleanup
    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_empty_rows_are_skipped(team, coach_user):
    csv_text = "name,number\nReal Player,5\n,\n  ,\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


# ---------- template ----------

def test_template_csv_downloads_publicly():
    r = requests.get(f"{BASE_URL}/api/players/import-template.csv")
    assert r.status_code == 200
    body = r.text
    # iter58: template now includes birth_year and current_grade columns
    assert body.startswith("name,number,position,birth_year,current_grade")
    assert "Jane Doe" in body
    assert r.headers.get("content-disposition", "").startswith("attachment")


def test_template_includes_demographic_examples():
    """The downloadable template should show coaches *how* to fill demographics."""
    r = requests.get(f"{BASE_URL}/api/players/import-template.csv")
    body = r.text
    # At least one example row has a 4-digit birth year and a grade label
    assert "2008" in body or "2007" in body or "2009" in body
    assert "Junior" in body or "Senior" in body or "Sophomore" in body


# ---------- iter58: birth_year + current_grade ----------

def test_import_with_canonical_demographic_headers(team, coach_user):
    """birth_year + current_grade columns (canonical names) round-trip correctly."""
    csv_text = (
        "name,number,position,birth_year,current_grade\n"
        "Demo Alpha,11,ST,2008,11th (Junior)\n"
        "Demo Beta,12,CM,2009,10th (Sophomore)\n"
    )
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2
    # Verify parsed payload carries the demographic fields
    by_name = {p["name"]: p for p in body["parsed"]}
    assert by_name["Demo Alpha"]["birth_year"] == 2008
    assert by_name["Demo Alpha"]["current_grade"] == "11th (Junior)"
    assert by_name["Demo Beta"]["birth_year"] == 2009
    # And the DB row persisted the fields
    r2 = requests.get(f"{BASE_URL}/api/players/team/{team['id']}", headers=coach_user["headers"])
    rows = {p["name"]: p for p in r2.json()}
    assert rows["Demo Alpha"]["birth_year"] == 2008
    assert rows["Demo Alpha"]["current_grade"] == "11th (Junior)"
    assert rows["Demo Beta"]["birth_year"] == 2009

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_import_accepts_demographic_header_aliases(team, coach_user):
    """Aliases like 'YOB' / 'Year of Birth' / 'Class' / 'Grade' should resolve."""
    csv_text = (
        "Player Name,YOB,Class\n"
        "Alias Player,2010,9th (Freshman)\n"
    )
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1
    parsed = body["parsed"][0]
    assert parsed["birth_year"] == 2010
    assert parsed["current_grade"] == "9th (Freshman)"

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_import_extracts_year_from_full_date(team, coach_user):
    """If a coach pastes a full birthdate (e.g. '2008-05-12'), we still extract 2008."""
    csv_text = "name,birth year\nDate Test,2008-05-12\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    parsed = r.json()["parsed"][0]
    assert parsed["birth_year"] == 2008

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_import_rejects_implausible_birth_year(team, coach_user):
    """A birth_year that makes the player <5 or >30 years old is reported as an error
    and the row imports with birth_year=None."""
    csv_text = "name,birth_year\nToo Old,1900\nToo Young,2025\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    # Both rows still import (the row is preserved; only the bad field is dropped)
    assert body["imported"] == 2
    # And we surface a warning for each
    reasons = " ".join(e["reason"] for e in body["errors"])
    assert "1900" in reasons
    assert "2025" in reasons
    # Birth years are null on the parsed payload
    parsed = {p["name"]: p for p in body["parsed"]}
    assert parsed["Too Old"]["birth_year"] is None
    assert parsed["Too Young"]["birth_year"] is None

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_import_demographics_are_optional(team, coach_user):
    """Existing 3-column rosters (no birth_year/current_grade) still import cleanly."""
    csv_text = "name,number,position\nLegacy Player,7,LM\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1
    parsed = body["parsed"][0]
    assert parsed["birth_year"] is None
    assert parsed["current_grade"] is None

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


# ---------- BOM handling ----------

def test_excel_bom_is_handled(team, coach_user):
    # Excel saves CSVs with a UTF-8 BOM that defeats naive parsers.
    csv_text = "\ufeffname,number\nBOM Test,42\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


# ---------- iter59: Hudl / TeamSnap CSV exports ----------

def test_hudl_style_split_name_columns(team, coach_user):
    """Hudl exports have First Name + Last Name columns instead of a single name."""
    csv_text = (
        "First Name,Last Name,Jersey,Position,Date of Birth,Grad Year\n"
        "Jamie,Rivers,7,Forward,2009-03-12,2028\n"
        "Alex,Park,2,Defender,2008-11-04,2027\n"
    )
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2
    by_name = {p["name"]: p for p in body["parsed"]}
    # Combined first+last
    assert "Jamie Rivers" in by_name
    assert "Alex Park" in by_name
    # DOB year extracted
    assert by_name["Jamie Rivers"]["birth_year"] == 2009
    assert by_name["Alex Park"]["birth_year"] == 2008
    # Grad Year → grade label derived (currently Feb 2026, school_year_end=2026):
    #   2028 - 2026 = 2 → 10th (Sophomore)
    #   2027 - 2026 = 1 → 11th (Junior)
    assert by_name["Jamie Rivers"]["current_grade"] == "10th (Sophomore)"
    assert by_name["Alex Park"]["current_grade"] == "11th (Junior)"

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_teamsnap_style_member_type_skips_coaches(team, coach_user):
    """TeamSnap exports include Member Type — only 'Player' rows should import."""
    csv_text = (
        "Full Name,Jersey Number,Member Type\n"
        "Player One,11,Player\n"
        "Head Coach,,Coach\n"
        "Player Two,12,Player\n"
        "Team Manager,,Manager\n"
    )
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2, body
    assert body["skipped"] == 2  # Coach + Manager rows
    names = sorted(p["name"] for p in body["parsed"])
    assert names == ["Player One", "Player Two"]

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_split_name_with_no_first_or_last_skips_row(team, coach_user):
    """If both first and last are blank, treat the row as empty (no crash)."""
    csv_text = "First Name,Last Name\nValid,Player\n,\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1


def test_grad_year_without_current_grade_column(team, coach_user):
    """A roster with only Grad Year (no Grade column) should still get a grade derived."""
    csv_text = "name,Grad Year\nSeniorish,2026\nFreshmanish,2029\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 200, r.text
    parsed = {p["name"]: p for p in r.json()["parsed"]}
    # Feb 2026, school year end = 2026:
    #   2026-2026=0 → 12th (Senior); 2029-2026=3 → 9th (Freshman)
    assert parsed["Seniorish"]["current_grade"] == "12th (Senior)"
    assert parsed["Freshmanish"]["current_grade"] == "9th (Freshman)"

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_explicit_grade_wins_over_grad_year(team, coach_user):
    """If both Grade and Grad Year are present, explicit Grade takes priority."""
    csv_text = (
        "name,grade,grad year\n"
        "Conflicted,Graduate / Post-Grad,2030\n"
    )
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    parsed = r.json()["parsed"][0]
    assert parsed["current_grade"] == "Graduate / Post-Grad"

    async def go():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
    _run_async(go())


def test_missing_name_columns_returns_helpful_error(team, coach_user):
    """When NEITHER 'name' NOR 'First Name + Last Name' is found, error message
    should mention the Hudl/TeamSnap split-name fallback."""
    csv_text = "Jersey,Position\n9,ST\n"
    r = _post_csv(team["id"], coach_user["headers"], csv_text)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "name" in detail
    assert "first name" in detail and "last name" in detail
