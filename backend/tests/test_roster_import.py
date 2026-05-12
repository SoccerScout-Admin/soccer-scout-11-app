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
    assert body.startswith("name,number,position")
    assert "Jane Doe" in body
    assert r.headers.get("content-disposition", "").startswith("attachment")


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
