# Soccer Scout - Product Requirements Document

## Problem Statement
Build a site to upload soccer match videos for in-depth game analysis. Features include video uploading, match creation, AI analysis of gameplay, manual annotations, video clipping/trimming, and downloadable highlights.

## Tech Stack
- **Frontend**: React 19, React Router 7, Tailwind CSS, Phosphor Icons, Axios
- **Backend**: FastAPI, Motor (async MongoDB), JWT auth, bcrypt
- **Database**: MongoDB
- **AI**: Gemini 3.1 Pro (via Emergent LLM Key + emergentintegrations)
- **Storage**: Emergent Object Storage (primary), `/var/video_chunks/` filesystem (fallback)
- **Video**: ffmpeg for clip extraction

## Architecture
```
/app/
├── backend/
│   ├── server.py (1560+ lines - monolithic, all routes/models/logic)
│   ├── requirements.txt
│   └── .env (MONGO_URL, DB_NAME, EMERGENT_LLM_KEY, JWT_SECRET)
├── frontend/
│   ├── src/
│   │   ├── App.js (Router, auth helpers)
│   │   ├── pages/
│   │   │   ├── AuthPage.js (Login/Register)
│   │   │   ├── Dashboard.js (Match library + folder sidebar)
│   │   │   ├── MatchDetail.js (Upload + player roster)
│   │   │   └── VideoAnalysis.js (Video player, AI tabs, clips, annotations)
│   │   └── components/ui/ (Shadcn components)
│   └── .env (REACT_APP_BACKEND_URL)
├── scripts/
│   └── setup.sh (ffmpeg install, /var/video_chunks dir)
└── /var/video_chunks/ (84GB overlay for chunk storage)
```

## Key DB Collections
- `users`: {id, name, email, password, role, created_at}
- `matches`: {id, user_id, team_home, team_away, date, competition, video_id, folder_id}
- `videos`: {id, user_id, match_id, processing_status, chunk_paths, ...}
- `folders`: {id, user_id, name, parent_id, is_private, created_at}
- `players`: {id, user_id, match_id, name, number, position, team, created_at}
- `annotations`: {id, user_id, video_id, timestamp, annotation_type, content, player_id}
- `clips`: {id, user_id, video_id, match_id, title, start_time, end_time, clip_type, player_ids}
- `analyses`: {id, user_id, video_id, match_id, analysis_type, content, status, auto_generated}

## What's Been Implemented

### Core Features (Complete)
- JWT authentication (register/login)
- Match CRUD with folder assignment
- 10GB+ chunked video upload with auto-resume
- Hudl/Veo-like auto-processing pipeline (Gemini 3.1 Pro)
- Server-restart resilience (heartbeat polling, startup auto-resume)
- Manual annotations (note, tactical, key_moment)
- Video clips with type classification
- Downloadable highlights package (JSON)

### Folders System (Complete - Apr 28, 2026)
- Nested folder structure with iterative flat-tree rendering
- Create/edit/delete folders with parent selection
- Public/private toggle per folder
- Folder sidebar on Dashboard with match count
- Match filtering by folder, move-to-folder dropdown
- Delete folder cascades: children & matches move to parent

### Player Rosters (Complete - Apr 28, 2026)
- Manual player add (name, number, position, team)
- CSV import (name,number,position columns + team selection)
- Players grouped by team on MatchDetail page
- Player tagging in annotations (single select)
- Player tagging in clips (multi-select toggle)
- Delete individual players
- AI prompts enriched with roster data for player-specific analysis

### AI Analysis Error Handling (Complete - Apr 28, 2026)
- Fixed processing_status logic: properly marks "failed" when all analyses fail
- Budget/quota error detection in frontend with user-friendly messaging
- Processing-failed banner correctly displays for failed videos
- Retry/resume processing for failed types

### Shareable Game Film Links (Complete - Apr 28, 2026)
- Public share links for folders (no login required for viewers)
- Toggle sharing from folder context menu with share modal
- Copy-to-clipboard with fallback for iframe/sandbox contexts
- Revoke sharing explicitly from modal (prevents accidental revocation)
- Public SharedView page: folder listing, match detail with video player, analysis tabs, clips, annotations, roster
- Green share indicator icon on shared folders in sidebar
- Invalid/expired links show clean "Link Unavailable" error page

### Video Analysis Upgrade: Full-Match + Trimming + Timeline + Downloads (Complete - Apr 28, 2026)
- Full match compression: Entire video compressed to 360p/12fps (<500MB) for Gemini instead of 30-sec samples
- AI Timeline Markers: Gemini identifies goals, shots, saves, fouls with timestamps → colored markers on video timeline (Hudl/Veo style)
- Click any marker to jump to that moment; legend shows event type counts
- Video Trimming: "Trim & Analyze" panel lets coaches select start/end time to analyze a specific section
- Downloadable Clips: "Download MP4" button on each clip extracts actual video via ffmpeg
- New "Timeline" tab showing all AI-detected events in chronological order

### Team Management + Player Registration + Clip Sharing + Auto-clips (Complete - Apr 29, 2026)
- Team Management: Create teams with name, season (e.g. "2025/26"), club. Multiple teams/seasons per coach.
- Player Registration: Players tied to Team + Season via team_id. Profile picture upload to Object Storage.
- Clip Sharing: Individual clips get shareable public links. Public endpoint returns clip metadata + video stream.
- Auto-clip from AI Markers: When timeline markers are generated, clips are automatically created with:
  - Goals/shots/saves/chances: 8s before + 8s after event
  - Fouls/cards: 20s before + 5s after event
- Backend refactored: New route modules in /app/backend/routes/ (teams.py, players.py, clips.py, auth.py)
- ffmpeg auto-installs at server startup if missing

### Backlog Items Cleared (Complete - Apr 29, 2026)

**1. Background sweeper for soft-deleted videos**
- New `deleted_video_sweeper()` async task launched at startup; runs hourly; permanently deletes videos with `is_deleted=true` AND `deleted_at < now-24h`. Storage chunks were already cleaned at delete time, so this just tidies the metadata records.

**2. Per-club share page**
- `POST /api/clubs/{id}/share` toggle, public `GET /api/shared/club/{token}` returning club crest + name + all teams (with player counts and per-team share tokens for chained navigation).
- OG card endpoints `/api/og/club/{token}` + `.png` (reuses the team-card layout with crest on the right).
- New `/shared-club/:token` route → `SharedClubView.js` with hero (crest + name + N teams + M players + director credit), team cards that link to `/shared-team/:token` when a team's roster is also publicly shared.
- ClubManager: added a 3rd action ("Share") on the club hover row, modal mirrors the team-share UX with copy-OG-URL + revoke flow.

**3. Bulk match operations**
- Backend: `POST /matches/bulk/move` (move many → folder or root), `/matches/bulk/competition` (set same competition string), `/matches/bulk/delete` (cascade-delete clips/analyses/markers + soft-delete associated videos so the 24h restore window applies).
- Dashboard: yellow "Select" toggle activates selection mode → checkbox overlays on each match card → sticky bulk action bar with Move-to-folder dropdown, "Set Competition" prompt, "Delete" button. "Done" exits the mode.

**4. AI jersey-number detection (auto-tag)**
- New `POST /api/clips/{id}/ai-suggest-tags`: extracts a single 854px-wide JPEG frame at the clip's mid-point with FFmpeg (`-ss <ts> -frames:v 1 -vf scale=854:-1`), sends it to Gemini 2.5 Flash via `LlmChat` + `FileContentWithMimeType` with a strict-JSON prompt asking for visible jersey numbers, parses `{"jersey_numbers": [...]}`, then matches each number to roster players (`team_ids` aware).
- VideoAnalysis tag modal: new gradient "AI Suggest Players" button at the top — runs the detection, pre-selects matched players, and shows an inline status: `AI detected jersey #7, #10 — 2 matched to roster`. Coach can then de-select before saving — keeps human-in-the-loop.

**All four verified**: 23/23 regression sweep still passes after the additions. Screenshots confirm bulk-mode UI + public club page render correctly.

### server.py Refactor + Restore-Deleted-Video (Complete - Apr 29, 2026)

**Restore deleted videos (24h grace window)**
- New `GET /api/matches/{id}/deleted-videos` returns videos with `is_deleted=true` and `deleted_at >= now-24h`.
- New `POST /api/videos/{id}/restore` validates the 24h window, refuses to clobber an already-attached video on the same match (HTTP 409), then unsets `is_deleted` + `deleted_at` and re-attaches `match.video_id` + `match.duration`.
- MatchDetail.js gained a "Recover a recently deleted video" link in the upload state and a drawer listing each deleted video with its filename, deletion timestamp, and a green "Restore" button.
- Note: restore reattaches the video file only — clips/AI analyses/markers cascade-deleted at delete time are not recoverable. UI confirmation explains this clearly.

**server.py refactor (CRUD-style routes extracted)**
- New `routes/folders.py` (204 lines) — folder CRUD + folder sharing (toggle, public folder view, public match detail). The public video stream endpoint stays in server.py because it depends on `read_chunk_data` from the chunked-upload pipeline.
- New `routes/matches.py` (98 lines) — match CRUD + the new `/matches/{id}/deleted-videos` endpoint.
- New `routes/annotations.py` (61 lines) — annotation CRUD.
- New `routes/analysis.py` (61 lines) — read endpoints `/analysis/video/{id}`, `/highlights/video/{id}`, `/markers/video/{id}`. The AI-generation endpoints (`/analysis/generate`, `/process/...`, reprocess, trimmed) stay in server.py because they import the auto-processing pipeline + Gemini integration that would create circular dependencies.
- All four routers mounted in server.py via the established `_api = APIRouter(prefix="/api"); include_router; app.include_router` pattern.
- Result: server.py shrank from ~2510 → 2292 lines. Routes directory is now the single source of truth for 70+ endpoints across 8 domains (auth/teams/players/player_profile/clips/og/folders/matches/annotations/analysis).
- **Verified**: full 23/23 regression sweep passes after the refactor — zero behavior change.

### Replace / Re-upload Match Video (Complete - Apr 29, 2026)
- New `DELETE /api/videos/{id}` endpoint: soft-deletes the video (sets `is_deleted=true`, records `deleted_at`), unlinks `match.video_id` + `match.duration` + `match.processing_status`, hard-deletes derived `clips` / `analyses` / `timeline_markers`, and best-effort cleans both object-storage chunks and on-disk `/var/video_chunks/{video_id}` directories so the next upload starts fresh. Also drops orphaned `chunked_uploads` session records.
- MatchDetail.js now polls `/api/videos/{id}/processing-status` every 5s when a video is attached and shows a colored status chip (`AI ready` / `Processing… N%` / `Processing failed`).
- New "Replace Video" button next to "View Analysis" → confirmation modal listing exactly what will be removed (video file, clips, AI markers/analyses) vs preserved (match, roster, folder, share links). After delete, MatchDetail seamlessly returns to its upload state without forcing a page reload.
- Cascade verified end-to-end: seeded a fake video + clip + analysis + marker, called DELETE, confirmed all derived rows gone and match unlinked. (sets `is_deleted=true`, records `deleted_at`), unlinks `match.video_id` + `match.duration` + `match.processing_status`, hard-deletes derived `clips` / `analyses` / `timeline_markers`, and best-effort cleans both object-storage chunks and on-disk `/var/video_chunks/{video_id}` directories so the next upload starts fresh. Also drops orphaned `chunked_uploads` session records.
- MatchDetail.js now polls `/api/videos/{id}/processing-status` every 5s when a video is attached and shows a colored status chip (`AI ready` / `Processing… N%` / `Processing failed`).
- New "Replace Video" button next to "View Analysis" → confirmation modal listing exactly what will be removed (video file, clips, AI markers/analyses) vs preserved (match, roster, folder, share links). After delete, MatchDetail seamlessly returns to its upload state without forcing a page reload.
- Cascade verified end-to-end: seeded a fake video + clip + analysis + marker, called DELETE, confirmed all derived rows gone and match unlinked.

### Clip Player Tagging UI + Backend Hardening (Complete - Apr 29, 2026)
- New `PATCH /api/clips/{id}` endpoint accepts partial updates (title/description/clip_type/player_ids). When `player_ids` is set, validates every id belongs to the current user (returns 400 with helpful message if not).
- VideoAnalysis sidebar: each clip got a yellow "Tag" / "Tags (N)" button next to Play/Download/Share. Opens a modal with a search box (by name or jersey #) listing the entire roster as toggleable cards (yellow checkbox + jersey + name + position). "Save Tags" persists via PATCH; PlayerProfile and SharedPlayerProfile now show real stats and highlight reels populated by these tags.
- `ClipCollectionCreate.clip_ids` capped at `max_length=200` to prevent abuse.
- **Regression sweep run** via testing agent: 23/23 endpoints passed including PATCH/profile aggregation/all 5 share variants (folder/team/player/clip/clip-collection) + their OG html + 1200×630 PNGs, multi-team season cap, promote, eligible-players, public payload sanitization. Sweep saved at `/app/backend/tests/test_regression_sweep.py` (idempotent — re-runs safely).
- Stale `test_shared_folders.py` token from previous fork updated to current value (`0c1c5e1a-b80`). When `player_ids` is set, validates every id belongs to the current user (returns 400 with helpful message if not).
- VideoAnalysis sidebar: each clip got a yellow "Tag" / "Tags (N)" button next to Play/Download/Share. Opens a modal with a search box (by name or jersey #) listing the entire roster as toggleable cards (yellow checkbox + jersey + name + position). "Save Tags" persists via PATCH; PlayerProfile and SharedPlayerProfile now show real stats and highlight reels populated by these tags.
- `ClipCollectionCreate.clip_ids` capped at `max_length=200` to prevent abuse.
- **Regression sweep run** via testing agent: 23/23 endpoints passed including PATCH/profile aggregation/all 5 share variants (folder/team/player/clip/clip-collection) + their OG html + 1200×630 PNGs, multi-team season cap, promote, eligible-players, public payload sanitization. Sweep saved at `/app/backend/tests/test_regression_sweep.py` (idempotent — re-runs safely).
- Stale `test_shared_folders.py` token from previous fork updated to current value (`0c1c5e1a-b80`).

### Public Player Dossier (Complete - Apr 29, 2026)
- **Schema**: `Player.share_token: Optional[str]` added.
- **Backend**: `POST /api/players/{id}/share` toggles a 12-char share token. Public `GET /api/shared/player/{token}` returns sanitized payload (only id/name/number/position/profile_pic_url/team — `user_id`, `match_id`, `team_ids`, etc. stripped) plus owner coach name, teams (joined to actual team docs), aggregated stats by clip type, and the highlight reel of clips. Each highlight clip is auto-granted a share_token so the existing public stream endpoint serves the video.
- **OG card** at `/api/og/player/{token}` + `/image.png`: branded 1200×630 PNG with "PLAYER PROFILE" label, jersey #, name, position + teams summary, top-4 stat chips (Goals/Saves/Fouls/Cards), circular profile pic with blue ring, "Shared by Coach …" credit. Title: `#N Name — Position`.
- **Frontend**:
  - `PlayerProfile.js` got a header "Share Profile" button with green "Shared" indicator + modal (copy/revoke flow matching team share UX, includes "Open public dossier in new tab" deep link).
  - New `SharedPlayerProfile.js` at `/shared-player/:token` mirrors the auth page's hero/stats/teams/highlight-reel sections but is fully public, branded "Player Dossier", with a header copy-link button. Clicking a highlight clip opens an inline video modal that streams via `/shared/clip/{token}/video` (no auth required).
- Verified end-to-end: toggle on/off, sanitized payload (no `user_id` leak), OG html + 1200×630 PNG, public dossier page renders with hero + team history + footer.

### Player Profile + Season Stats + Batch Clip-Reel Share (Complete - Apr 29, 2026)
- **`/player/:id` page** (`PlayerProfile.js`): hero with avatar/jersey/position, career stats grid (total clips, total time, per-type counts: goals/saves/fouls/cards/shots/chances/highlights with color-coded icons), team history grouped by season (chips link directly to each team's roster), highlight reel grid sorted by recency.
- New backend endpoint `GET /api/players/{id}/profile` aggregates from `clips` collection (counts by `clip_type`) + joins matches into clips for display context.
- Players in `TeamRoster.js` now click-through to their profile page; pic-upload + delete buttons preserved via `stopPropagation`.
- **Batch clip share (Clip Reels)**: new collection `clip_collections {id, title, clip_ids[], share_token, user_id}`.
  - Backend: `POST /api/clip-collections`, `GET /api/clip-collections`, `DELETE`, public `GET /api/shared/clip-collection/{token}` returns ordered clips with auto-granted share tokens for streaming, plus match enrichment.
  - OG card endpoint: `/api/og/clip-collection/{token}` + `/image.png` (reusing `render_folder_card` with custom `CLIP REEL` label).
  - VideoAnalysis sidebar: "Share N as Reel" button (purple) appears alongside the existing ZIP download whenever clips are checkbox-selected. Modal lets user title the reel and copies the OG-friendly URL with green "Smart link" indicator.
  - New public viewer `SharedClipCollectionView.js` at `/clips/:token`: video player + side playlist, copy-link CTA in header, branded footer, 404 fallback for revoked tokens.
- Routes mounted via new `routes/player_profile.py` + extended `routes/og.py`.
- Verified end-to-end via curl: profile aggregation ✓, collection create with title ✓, public payload ✓, OG html + 1200×630 PNG ✓, screenshot of the rendered profile page ✓.

### Multi-Team Players + Promote Roster (Complete - Apr 29, 2026)
- **Data model**: `Player.team_id` (single, optional) → `team_ids: List[str]`. One-time migration converted all existing players' `team_id` strings into single-element arrays.
- **Backend validation**: `_enforce_season_cap` blocks any insert/update that would put a player on more than 2 teams sharing the same `season` string.
- **New endpoints in `routes/players.py`**:
  - `POST /api/players/{player_id}/teams/{team_id}` — add existing player to additional team (validates cap)
  - `DELETE /api/players/{player_id}/teams/{team_id}` — remove player from one team (record stays if other teams remain)
  - `GET /api/teams/{team_id}/eligible-players` — players already on a different team in this team's season, with `at_cap` flag
  - `POST /api/teams/{team_id}/promote` — clones the team into a new season inside the same club and copies the roster (default `keep_old=true` so players appear on both)
- All `team_id` queries across `routes/teams.py` (player_count, get_team_players, public team share, OG card) updated to query `team_ids` array containment.
- Duplicate `/api/players` endpoints in `server.py` removed; `routes/players.py` now mounted as the single source of truth.
- **Frontend `ClubManager.js`**: green "Promote" button on each team row → modal with auto-suggested next season string (parses "YYYY/YY" → bumps both years by 1), pre-filled team name, "keep players on old roster" checkbox.
- **Frontend `TeamRoster.js`**: new "Add Existing" header button → modal lists same-season eligible players with their other team affiliations and an "At cap" badge for blocked candidates. Delete button now smartly chooses between "remove from this team only" (multi-team) vs full delete (last team) based on how many teams the player has.
- Verified via curl: cap enforcement, promote with 4 players, add-existing across seasons, delete-from-one-team flows all working. Frontend modals captured via screenshots.

### Club → Team Hierarchy + OG Cards Everywhere (Complete - Apr 29, 2026)
- **ClubManager UI** rebuilt: each club is now a collapsible card containing its nested teams. Per-club "Add Team" CTA pre-fills the club. Empty clubs show a dashed "Add first team to {Club}" button. Teams not assigned to any club fall into a separate "Unaffiliated Teams" section. Aggregate "N teams • M players total" summary on each club header.
- One-time data migration ran: existing teams that referenced a club by name string instead of UUID were repointed to the proper club id.
- **OG card pattern extended to folders + clips**: new `routes/og.py` exposes `/api/og/folder/{token}` + `/image.png` and `/api/og/clip/{token}` + `/image.png`. Color-coded clip cards (goal=green, save=blue, foul=red, card=amber, default=blue) with big play triangle. Folder cards include match-preview chips for the most recent 3 matches.
- Dashboard folder share modal + VideoAnalysis clip share modal now copy the OG-friendly URL by default with green "Smart link" indicator and a "Open public … in new tab" deep link below.
- All endpoints verified end-to-end: 1200×630 PNGs render correctly, OG/Twitter meta tags set, `X-Forwarded-Host` resolves the public URL.
- New `POST /api/teams/{team_id}/share` toggles a share token on the team
- New public `GET /api/shared/team/{share_token}` returns sanitized team info, club crest, full roster (only id/name/number/position/profile_pic_url — no internal fields), and any matches whose parent folder is publicly shared (with a folder share token for chained navigation)
- Share button + modal on TeamRoster.js (copy/revoke flow matching the folder share UX)
- New public route `/shared-team/:shareToken` rendered by `SharedTeamView.js` — Hero header, position-grouped squad cards with photos, "Recent Match Film" section linking out to the existing folder shared view
- 404 fallback ("Link Unavailable") for revoked tokens
- **OG unfurl prerender**: `GET /api/og/team/{token}` serves SSR HTML with og:title, og:description, og:image, Twitter card meta tags, then JS-redirects browsers to `/shared-team/:token`. Crawlers (WhatsApp, Slack, Twitter, Discord, FB) read static HTML for rich previews.
- **Dynamic 1200×630 OG card image**: `GET /api/og/team/{token}/image.png` renders a Pillow-generated branded card per request — gradient background, team name, club, season, player count, up to 6 player avatars (with "+N more" overflow badge), and Soccer Scout brand mark. Cached for 5 minutes via Cache-Control header.
- og:image URL uses `X-Forwarded-Host` / `X-Forwarded-Proto` so the public URL (not the internal cluster URL) is exposed to crawlers.
- Image generation isolated in `services/og_card.py` for testability.

### Team Roster Page + Profile Pic Upload UI (Complete - Apr 29, 2026)
- Dedicated `/team/:teamId` page (`TeamRoster.js`) for managing team-specific rosters per season
- Players grouped by position (Goalkeeper/Defender/Midfielder/Forward)
- Hover-to-reveal profile picture upload overlay on each player avatar
- Cache-busting on uploaded avatars so freshly uploaded photos render immediately
- Upload validates image MIME + 5MB cap; stored in Object Storage at `{APP}/players/{user}/{player}.{ext}`
- Backend `/api/players` accepts `team_id`; `/api/teams/{team_id}/players` returns roster

## Backlog

### P0 (Must Have)
- None currently blocking

### P1 (Should Have)
- Re-upload degraded videos (LFC vs Express 3%, LFC07BvsAYSO 8% data remaining) — filesystem chunks lost on container restart

### P2 (Nice to Have)
- Season stats dashboard per player (aggregate stats across matches)
- Batch share multiple clips at once (checkbox selection in VideoAnalysis.js → single shareable link)
- Refactor remaining `server.py` (matches, folders, analysis, videos) into route modules
- Decompose `VideoAnalysis.js` (~1176 lines) into Video Player + Timeline child components

## Test Credentials
- Email: testcoach@demo.com
- Password: password123
