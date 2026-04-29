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
