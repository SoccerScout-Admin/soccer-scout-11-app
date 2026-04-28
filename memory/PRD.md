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

## Backlog

### P0 (Must Have)
- None currently blocking

### P1 (Should Have)
- ffmpeg startup script persistence (currently manual install; `/app/scripts/setup.sh` created but needs integration into container startup)
- Video trimming/clipping & downloadable highlights packaging (actual video file stitching)
- Re-upload degraded videos (LFC vs Express 3%, LFC07BvsAYSO 8% data remaining) — filesystem chunks lost on container restart

### P2 (Nice to Have)
- Refactor `server.py` into route modules (auth, matches, folders, players, analysis, videos)
- Shareable public folder links
- Team management beyond per-match rosters

## Test Credentials
- Email: testcoach@demo.com
- Password: password123
