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

### Mobile Responsiveness Fix (Apr 29, 2026) — Critical bug fix
**User report**: "Create buttons are not working. Modal opens but does not create (nothing happens). Mobile Chrome browser."

**Root cause**: Dashboard layout was NOT mobile-responsive. On 390px mobile viewport:
- Document width was 619px (70% wider than viewport) → horizontal scroll
- Sidebar (`w-64 flex-shrink-0`) forced 256px even on mobile → main content squeezed off-screen
- Modal's inner `<div>` rendered at `x=-205` in bounding_box terms (mostly off-screen)
- When the virtual keyboard opened for input, the submit button went below the fold and was unreachable

**Fixes applied**:
- Dashboard layout → `flex flex-col lg:flex-row` (stacks sidebar above main content on mobile)
- Folder sidebar → `w-full lg:w-64 lg:flex-shrink-0` (full-width on mobile)
- Dashboard header → responsive: full Clubs/Coach-Network buttons on `sm+`, icon-only mobile versions on smaller screens
- All 9 modals across Dashboard / ClubManager / TeamRoster / ShareClipModal / ShareReelModal / TagPlayersModal → replaced `flex items-center justify-center` with `overflow-y-auto` + `mx-auto my-4 sm:my-8` so tall modals scroll within themselves and the submit button is always reachable above the mobile keyboard
- ClubManager header + inline Club form → mobile-responsive (buttons wrap to new row below input on small screens)

**Verified end-to-end on 390x844 viewport**:
- `docOverflow: 0` (was `619`)
- Create Match modal renders at `x=16, width=358` (was `x=-205, width=256`)
- POST /api/matches → 200, modal closes
- POST /api/folders → 200, modal closes
- POST /api/clubs → 200, inline form closes
- 80/80 backend regression tests still passing

### Coach Pulse Weekly Email Digest (Complete - Apr 29, 2026)
- New `routes/coach_pulse.py` (175 lines) — 6 endpoints:
  - `GET /api/coach-pulse/subscription` (auto-creates doc + returns is_active/last_sent/email)
  - `POST /api/coach-pulse/subscribe` + `POST /api/coach-pulse/unsubscribe` (auth-gated toggle)
  - `GET /api/coach-pulse/preview` (renders authenticated HTML preview)
  - `POST /api/coach-pulse/send-test` (live Resend send to current user)
  - `POST /api/coach-pulse/send-weekly` (admin-only blast with idempotency: skips users already sent this ISO week)
  - `GET /api/coach-pulse/unsubscribe/{token}` (public token-based opt-out from email footer)
- New `services/coach_pulse_email.py` (130 lines) — pure-string HTML template (table layout, inline CSS, email-client compatible). Personal stats grid + Coach Network anonymized section (top 5 weaknesses, top 5 strengths, position bars, recruit-level distribution). Network section gracefully degrades to "unlocks at 3+ coaches" callout when `network_ready=false`. Text fields capped at 120 chars to prevent layout-blowing.
- Refactored `routes/coach_network.py` to expose `compute_benchmarks(user_id?)` so coach_pulse can call it without going through the auth dep.
- Resend SDK integrated via `asyncio.to_thread` for non-blocking calls. RESEND_API_KEY + SENDER_EMAIL added to `/app/backend/.env`.
- New `pages/components/CoachPulseCard.js` (130 lines) — Dashboard card with cyan envelope icon, Subscribe/Subscribed toggle, Preview button (Blob-URL pattern with Bearer auth), Send Test button with status chip. Sits above the existing Coach Network CTA on `/`.
- 16 pytest cases in `/app/backend/tests/test_coach_pulse.py` (subscription auto-create, subscribe/unsubscribe round-trip, preview HTML content, public unsubscribe valid+invalid token, send-test graceful 502, send-weekly admin-gate (403 for coach role), email template unit tests for both ready/not-ready paths). **80/80 across full backend test suite**.
- Verified end-to-end: HTML renders correctly with all sections, Subscribe toggle flips correctly, Resend integration works (sandbox-policy 502 surfaces gracefully in UI).

### Coach Annotation Templates (Complete - Apr 29, 2026)
- New `routes/annotation_templates.py` (113 lines) — 4 endpoints scoped per-user + per annotation_type:
  - `GET /api/annotation-templates[?annotation_type=note|tactical|key_moment]` — sorted by usage_count desc + created_at asc; lazy-seeds 10 default phrases on first call (3 note + 4 tactical + 3 key_moment).
  - `POST /api/annotation-templates` — duplicate-detection (returns existing id with `duplicate: true` for same user + type + text).
  - `POST /api/annotation-templates/{id}/use` — increments usage_count so most-used phrases float to the top.
  - `DELETE /api/annotation-templates/{id}`.
  - Cross-user isolation enforced; user_id stripped from responses.
- New `pages/components/AnnotationForm.js` (142 lines) replaces inline form in VideoAnalysis.js — adds chip row above textarea (top 6 templates filtered by current annotationMode), one-click apply (fires /use), purple "Save as template" button next to Save Annotation that hides when text matches an existing template, optimistic re-sort.
- 18 pytest cases in `/app/backend/tests/test_annotation_templates.py` covering seed, filter, sort, auth, create+duplicate, use+reorder, delete, isolation. **18/18 passing.**

### Coach Network Contextual Surfacing (Complete - Apr 29, 2026)
- **MatchInsights.js**: fetches `/api/coach-network/benchmarks`; renders `network-chip-strength-{i}` / `network-chip-weakness-{i}` purple chips ("N COACHES ALSO") next to each match strength/weakness when fuzzy match (≥2 shared meaningful words length≥4, with stop-word filter for noise like "team/play/goal/minute") hits a `common_strengths_across_coaches` / `common_weaknesses_across_coaches` entry. Chips correctly hide when network not ready (k<3 coaches).
- **PlayerSeasonTrends.js**: fetches benchmarks; renders `platform-percentile-chip` ("X% of platform-rated players land at <level> (n/total)") below scout score rationale when player's `estimated_level` appears in `recruit_level_distribution` with ≥3 total ratings. Extracted into `<NetworkPercentileChip>` for symmetry with `<NetworkChip>` in MatchInsights.
- Verified end-to-end: seeded 3 fake coaches with shared "Foul management"/"Strong goalkeeping" themes → chips rendered correctly; seeded 3 player trends at "Youth Competitive" → percentile chip showed "100% of platform-rated players land at Youth Competitive (4/4)". Test data cleaned up post-verification.

### VideoAnalysis Decomposition — Final 4 Blocks Extracted (Complete - Apr 29, 2026)
- **`VideoAnalysisHeader.js`** (131 lines) — sticky header with match title/competition/date + back button + Download Package CTA + GB chip + processing banner (spinner, progress bar, 4-type status icons) + processing-failed banner with retry/resume CTA. Pure presentational.
- **`TrimPanel.js`** (58 lines) — start/end time inputs with "Now" snap-to-currentTimestamp buttons + 3 analyze CTAs (tactical/player_performance/highlights). `videoDuration || Infinity` guard so users can type values before metadata loads (was a latent bug in inline JSX).
- **`ClipsSidebar.js`** (136 lines) — composed of `ClipCard` sub-component + parent that handles batch selection (Share-as-Reel + Download-as-ZIP buttons appear when ≥1 selected, Download-All-ZIP always visible).
- **`AnnotationsSidebar.js`** (53 lines) — coach notes panel with timestamp pill + delete + jump-to-moment buttons.
- **`utils/time.js`** (8 lines) — shared `formatTime(seconds)` helper. Replaces 4 duplicate copies across VideoPlayerWithMarkers / AnalysisTabs / TrimPanel / ClipsSidebar / AnnotationsSidebar.
- VideoAnalysis.js: 1077 → 821 lines (-256, -24%). Across the entire P2 effort: **1266 → 821 lines (-35%)**.
- Verified: testing_agent_v3_fork ran a focused frontend regression — zero ui_bugs, zero integration_issues, zero design_issues, all data-testids unique, all callbacks correctly wired, no console errors. Backend 35/35 still passing.

### server.py Refactor — Video Routes Extracted (Complete - Apr 29, 2026)
- New `routes/videos.py` (111 lines) holds the 3 read-only video endpoints: `GET /api/videos/{video_id}/access-token` (5-min JWT for stream URLs), `GET /api/videos/{video_id}/metadata` (with chunks_available/chunks_total/data_integrity for chunked videos), `GET /api/videos/{video_id}/processing-status` (with completed_types/failed_types from analyses + server_boot_id).
- Cached lazy-import for `SERVER_BOOT_ID` (read once, reused) avoids circular import with server.py.
- Old duplicate definitions in server.py fully deleted — 2402 → 2331 lines.
- 12 new pytest cases in `/app/backend/tests/test_video_routes.py` (auth-required, 404 paths, payload schema, chunk integrity, completed-analyses reflection, no-410-shim verification). Combined with 23-case regression sweep: **35/35 passing**.
- Heavily-coupled endpoints (`/videos/{id}/reprocess`, `/analysis/generate`, `/analysis/generate-trimmed`, video streaming with Range, upload chunking, soft-delete) deliberately stay in server.py — they all depend on `run_auto_processing` / `read_chunk_data` / chunked-upload pipeline state.

### VideoAnalysis Decomposition — Analysis Tabs Extracted (Complete - Apr 29, 2026)
- New `pages/components/AnalysisTabs.js` (250 lines) — composed of `OverviewTab` (3-card summary + Start AI Processing CTA), `TimelineTab` (sortable AI marker list with click-to-seek), `AnalysisDetailTab` (handles tactical/player_performance/highlights with regenerate / generate states), wrapped by parent `AnalysisTabs` that owns the 5-tab nav and indicator dots (green for completed analyses, yellow for timeline with markers).
- Pure presentational; parent VideoAnalysis still owns all state and passes callbacks (`onSelectTab`, `onGenerate`, `onStart`, `onSeek`).
- VideoAnalysis.js: 1232 → 1076 lines (-156 lines, removed dead `getAnalysis` helper too). Combined with previous `VideoPlayerWithMarkers` extraction: 1266 → 1076 lines (-15%).
- Verified end-to-end: all 5 tabs render, click-to-seek works (clicked timeline event @ 0:17 → video.currentTime=17), green/yellow indicator dots correct, regenerate/generate flows preserved.

### Coach Network — Anonymized Platform Benchmarks (Complete - Apr 29, 2026)
- Backend `routes/coach_network.py` exposes `GET /api/coach-network/benchmarks` with k-anonymity threshold (≥3 coaches). Returns platform stats, per-coach distributions, position breakdown, recruit-level distribution, and the calling user's percentile bucket on matches/clips. Cross-coach themes (strengths/weaknesses) only surface when ≥3 coaches have hit the same pattern.
- Frontend `pages/CoachNetwork.js` at `/coach-network`: privacy-first banner, 5-card platform stats grid, "Your bucket on the platform" gradient card with percentile pills, Recharts position-bar chart, recruiter-level pie chart, side-by-side common-strengths/weaknesses panels.
- Wired into `App.js` as a protected route + Dashboard nav button (purple accent, header) + dashboard CTA card ("See how your coaching stacks up — anonymized") on the main content area.
- Verified end-to-end: backend returns full ready=true payload with 3-coach seed, frontend renders all sections correctly, percentile bucketing math verified.

### VideoAnalysis Decomposition — Video Player + Markers Strip (Complete - Apr 29, 2026)
- New `pages/components/VideoPlayerWithMarkers.js` (98 lines) — `forwardRef`-based child holding the `<video>` element, AI timeline markers strip (color-coded buttons positioned at `time/duration%`), and the markers legend. Parent retains direct ref control via forwarded ref so all `videoRef.current.currentTime` / `.play()` calls keep working unchanged.
- VideoAnalysis.js: 1266 → 1231 lines (35-line reduction; removed inline marker color map + legend entries that now live in the child).
- Verified: video src loads correctly, markers legend displays accurate counts (Shots/Saves/Fouls/Chances), 23/23 regression sweep still passes.

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

### Player Season Trends + Recruiter Lens (Complete - Apr 29, 2026)

**Backend (`routes/player_trends.py`)**
- `POST /api/players/{id}/season-trends?team_id=X` aggregates every clip tagged with the player_id, scoped to one of their teams (defaults to most recent season).
- Computes per-clip-type stats, total featured time, per-match clip distribution.
- Auto-detects position via `_normalize_position` (GK / Defender / Midfielder / Winger / Forward) and looks up a position-specific recruiter rubric — derived from US Soccer Development Academy / NCAA D1 / pro academy scout guides — listing the 5 attributes scouts evaluate plus what they specifically prioritize at each position.
- Sends a structured prompt to Gemini 2.5 Flash with the clip data + rubric, gets back JSON containing:
  - `player_summary` (verdict)
  - `team_role`: current_role + strengths_for_team + opportunities_for_team (scoped to *this team's needs*)
  - `recruiter_view`: estimated_level (Youth Recreational → Pro Academy), scout_score (1-10), per-rubric-attribute ratings with notes, where_they_excel, development_priorities
  - `recommended_drills` (3-4 tailored to development priorities)
- Cached on the player document keyed by team_id; `GET` returns cached.

**Frontend (`PlayerSeasonTrends.js` at `/player/:id/trends`)**
- Hero: avatar + jersey + name + position + team-season + AI verdict prose
- 4-card stats grid: Total Clips, Featured Time, Matches Active, Position
- "Role on {team}" panel with side-by-side Strengths (green) and Opportunities (yellow) — scoped to current team
- "Recruiter Lens" gradient card:
  - Left: Suggested Level pill (color-coded by recruitment tier: pink for Youth Recreational → purple for Pro Academy), 10-star rating, score-out-of-10, rationale
  - Right: Scout attributes table — each rubric attribute with progress bar (red <5, yellow 5-6, green ≥7) and notes
  - Below: "Where they excel" (green) + "Development priorities" (red)
- Recommended Drills cards (numbered, yellow accent)
- Multi-team selector in header (when player is on >1 team) lets coach switch season context

**Integration**: PlayerProfile gains a gradient "Season Trends" CTA in the header next to "Share Profile".

**Verified**: Real Gemini-generated GK report on a 3-clip dataset for Marcus Johnson — appropriately conservative ratings (6/10 shot stopping, 3/10 command of the box) reflecting limited sample, accurate position-specific rubric, grounded team-role analysis. Screenshot confirms layout. 23/23 regression sweep still passes.

### Season Trends — Aggregate Coaching Dashboard (Complete - Apr 29, 2026)
- New `routes/season_trends.py` — `POST /api/folders/{id}/season-trends` aggregates every match in a folder:
  - **Per-match scoreline** inferred from `markers` (counts goals by team)
  - **Record**: W / D / L counts
  - **Goal stats**: GF, GA, GD, clip type totals
  - **Recurring patterns**: top strengths + weaknesses across all matches' cached AI insights, ranked by frequency
  - **Season Verdict** (when ≥2 matches have insights): one Gemini 2.5 Flash call synthesizes a season-level brief — `verdict + trends + focus_for_training` — from the per-match summaries.
- Cached on the folder doc; `GET` returns cached.
- New `SeasonTrends.js` page at `/folder/:id/trends` with: hero record grid (W/D/L/GF-GA/GD), Recharts bar chart of goals per match, gradient season-verdict card with patterns + training focus, side-by-side recurring strengths/weaknesses, match-by-match timeline with result badges.
- Dashboard: gradient "Season Trends" CTA when a folder is filter-selected; folder context menu also has a quick link.
- Verified end-to-end: backend produced full structured payload for the existing 2-match folder; screenshot confirms layout including empty-state messaging when individual match insights haven't been generated yet (turn-by-turn UX).
- 23/23 regression sweep still passes.

### Match Insights + VideoAnalysis Decomposition + Processing Pipeline Extraction (Complete - Apr 29, 2026)

**Match Insights — AI coaching brief**
- New `routes/insights.py`: `POST /api/matches/{id}/insights` synthesises `markers + clips + roster + score → Gemini 2.5 Flash` into a structured JSON dossier (verdict + strengths + weaknesses + 3-5 numbered coaching points + 3-6 pivotal moments + score context). Cached on the match doc; `GET` returns cached or 404.
- New `MatchInsights.js` page at `/match/:id/insights`: purple-gradient verdict card, side-by-side strengths/weaknesses panels (green/red), numbered coaching cards (yellow), pivotal-moments timeline (blue clock chips), regenerate button.
- "AI Insights" button in MatchDetail header (yellow-purple gradient) launches the page.
- Verified end-to-end: Gemini returned a real, well-formatted brief with specific minute marks for an existing match — screenshot confirms layout.

**VideoAnalysis.js decomposition** (1463 → 1266 lines)
- New `pages/components/TagPlayersModal.js` (122 lines) — full search + AI-suggest + roster checkboxes
- New `pages/components/ShareReelModal.js` (88 lines) — bundle clips into shareable reel
- New `pages/components/ShareClipModal.js` (74 lines) — single-clip share with social buttons
- Parent VideoAnalysis still owns the modal-related state (lifted-up pattern, low-risk) and passes it down via props. Behavior preserved.

**Auto-processing pipeline partial extraction** (high regression risk explicitly flagged by user)
- New `services/processing.py` (199 lines) holds the *pure* helpers — `build_roster_context`, `build_analysis_prompts`, `parse_and_store_markers`, `run_single_analysis` — with `auto_create_clips_callback` as an injected dependency (no circular imports).
- Heavy orchestration (`run_auto_processing`, `prepare_video_sample`, `prepare_video_segments_720p`, FFmpeg multi-segment compression, circuit breaker state) **deliberately remains in server.py** because they have deep coupling with `read_chunk_data`, `processing_status` global state, and the chunked-upload pipeline. Moving these requires a focused session with AI-pipeline test coverage.
- server.py keeps backward-compatible shims so the existing call sites work unchanged.
- **23/23 regression sweep still passes** after the extraction.

**Final code structure:**
- server.py: 2402 lines (heavy AI/FFmpeg/streaming pipeline + remaining orchestration)
- 11 route modules (auth/teams/players/player_profile/clips/folders/matches/annotations/analysis/insights/og)
- 4 services (storage, processing, og_card, __init__)
- 3 frontend modal components
- Routes directory now serves 90+ endpoints across 11 domains.

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
- Re-upload degraded videos (LFC vs Express 3%, LFC07BvsAYSO 8% data remaining) — filesystem chunks lost on container restart, requires user action

### Future / Backlog
- **Admin role assignment** — currently no flow to promote a user to `admin`/`owner`. The `/coach-pulse/send-weekly` blast endpoint requires this role, so an admin-promotion mechanism is needed before the weekly blast can run.
- **Resend domain verification** — Once a custom domain is verified at resend.com/domains, swap `SENDER_EMAIL` away from `onboarding@resend.dev` so coach pulse emails can deliver to all subscribers (not just the Resend account owner).
- **APScheduler-based weekly cron** — currently `/send-weekly` is manual. Add a scheduled job that hits this endpoint every Monday 8am UTC with admin auth.
- Full extraction of AI auto-processing pipeline (`run_auto_processing`, `prepare_video_sample`, FFmpeg multi-segment compression) from `server.py` into `services/processing.py` — DEFERRED due to high regression risk on the core AI-pipeline / chunked-upload coupling
- Dedicated "Manage Templates" modal once a coach exceeds 6 saved templates
- Bulk-share clips picker on Dashboard (cross-match version)
- Season stats dashboard per player (aggregate across teams/seasons)
- Position-breakdown comparison on TeamRoster (network %s vs your team %s)

## Test Credentials
- Email: testcoach@demo.com
- Password: password123
