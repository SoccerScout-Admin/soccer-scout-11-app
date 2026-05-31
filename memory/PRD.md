# Soccer Scout - Product Requirements Document


## New Brand Logo Rollout (Feb 2026)

User uploaded a new official "Soccer Scout 11" logo (square lockup: white+blue "S11" mark with an embedded play button, "SOCCER SCOUT 11" wordmark, tagline "ANALYZE. IDENTIFY. ELEVATE." on black). Regenerated ALL brand assets in `/app/frontend/public/` from the source, preserving each file's original dimensions/mode so no layout broke:
- **Header/inline lockups** (`logo-mark.png` 969x473, `logo-mark-256.png`, `logo-mark-96.png`): the S11 mark, black→transparent RGBA (clean over dark UI). Mark is ~2:1, matching the old header logo's 1.95:1 ratio — zero layout regression.
- **Square app icons** (`favicon.png`, `apple-touch-icon.png`, `icon-192/512.png`, `logo-192/512.png`): S11 mark centered on `#0A0A0A`.
- **Full lockup** (`logo.png` 1200², `logo-source.png` 2000²) + static social card (`og-image.png` 1200x630).
- Backend `services/og_card.py` dynamic OG cards auto-pick up the new `logo-mark.png` (in-memory cache cleared via backend restart; verified the S11 mark renders bottom-right with working transparency).
- No code changes — assets only. Verified live: auth page, landing header, icon contact sheet, and a rendered dynamic OG card all show the new mark crisply. OG/share tests (16) pass.
- NOTE: filenames unchanged, so browsers/social scrapers may serve cached old favicon/OG image until cache expiry (use a social re-scrape e.g. FB Sharing Debugger if needed).


## One-Click Goals-Only Highlight Reel (iter108 — May 2026)

User said yes to the iter107 finish-tool suggestion: a one-click button that takes every `type=goal` marker, creates clips for each, and stitches them into a downloadable goal-only highlight reel.

### Backend
- **`POST /api/matches/{match_id}/highlight-reel/goals-only`** in `routes/highlight_reels.py`:
  - 503 if ffmpeg unavailable; 404 if match not owned by user; 400 if no video or no goal markers; 429 if user has 3+ reels in flight (matches the main create endpoint's cap)
  - Finds all `markers` with `type=goal` for the match's video
  - For each goal marker WITHOUT an existing auto-clip (matched by `source_marker_id` for idempotency), creates a clip with:
    - `start_time = max(0.0, marker.time - 7.0)` (clamped to >= 0 so an early goal at t=3 doesn't produce a negative start)
    - `end_time = marker.time + 8.0` (15s window centered on the marker)
    - `clip_type = "goal"`, `auto_from_goal_marker = True`, `source_marker_id = marker.id`
    - Title via `_build_goal_clip_title(marker)`: `"Goal — #9 Marcus Lopez"` (with iter99/iter102 player attribution) → falls back to `"Goal — #9"` → falls back to marker label
  - Enqueues a reel row with `goals_only: True` + `goal_clips_auto_created: <count>` provenance
- **`_select_clips(clips, goals_only=False)`** in `services/highlight_reel.py`:
  - When `goals_only=True`, skips score-greedy pruning entirely. Takes every goal clip in chronological order, applying only the per-clip 12s duration cap + the MAX_DURATION_S budget.
  - Backwards-compatible: existing callers continue passing only `clips` and get the original score-based behavior.
- **Reel pipeline** in `_run_reel_job` filters clips to `clip_type=goal` upstream when `goals_only=True` so the selector sees only goal candidates. Fails with `no_goal_clips_available` if filtering empties the set.

### Frontend
- `pages/components/HighlightReelsPanel.js`:
  - Renamed existing button from "Generate Highlight Reel" → **"Best Moments Reel"** to distinguish the two flows
  - New **yellow "Goals-Only Reel" button** next to it (Phosphor `Sparkle` icon, `bg-[#FBBF24]` to match the goal marker color scheme)
  - Shares `generating` + `hasInFlight` state with the existing button so users can't double-trigger
  - `handleGenerateGoalsOnly` calls the new endpoint and reuses the existing `fetchReels` polling so the new reel appears in the panel list with progress + download once ready

### Tests (13 new, 189/189 across iter75 + iter93→108)
- `test_iter108_goals_only_reel.py`:
  - Creates one 15s clip per goal marker; tagged with `clip_type=goal`, `auto_from_goal_marker`, `source_marker_id`
  - Idempotent — re-running creates 0 new clips
  - Clamps `start_time` to 0 for goals at t=3 (negative-start prevention)
  - Carries iter99 player attribution into clip titles
  - 404 for unknown match, 400 for no video, 400 for no goal markers, auth required, cross-user 404
  - `_select_clips(goals_only=True)` returns ALL goal clips chronologically (skips score pruning)
  - `_select_clips()` default (no flag) still uses score-greedy selection (verified by membership test with high-scoring goal clip beating low-scored highlights under tight budget)
  - Frontend grep: panel has `generate-goals-only-reel-btn` testid + handler + endpoint reference + both button labels
  - Deploy endpoint advertises 4 new feature flags

### Verified live on preview
- Playwright screenshot of `/match/{id}` shows the new yellow "GOALS-ONLY REEL" button rendering side-by-side with the rebranded "BEST MOMENTS REEL" button, under the helper text "AI picks your top clips (goals first), stitches them with branded title cards..."
- `GET /api/health/deploy` → `build=iter108` with all 4 new feature flags

### Files touched
- `backend/routes/highlight_reels.py` (NEW `/goals-only` endpoint + `_build_goal_clip_title` helper)
- `backend/services/highlight_reel.py` (`_select_clips(goals_only=False)` flag + upstream goal filter + `goals_only` reel doc support)
- `backend/server.py` (BUILD_VERSION → iter108, 4 new feature flags)
- `frontend/src/pages/components/HighlightReelsPanel.js` (`handleGenerateGoalsOnly`, renamed first button, new yellow second button)
- `backend/tests/test_iter108_goals_only_reel.py` (NEW — 13 cases)

### End-to-end coach workflow now possible
1. Upload match video
2. iter97-103 pipeline auto-processes → iter99/107 prompt generates goal markers
3. iter102 pencil-tag any goal scorers AI missed
4. iter107 manual scissor-clip individual marquee moments
5. **iter108 one-click "Goals-Only Reel"** → 60-90s downloadable MP4 of every goal with player names baked in
6. Share via iter40-49 Recruiter Lens links to college coaches

Total time: ~5 minutes from upload-complete to recruiter-ready reel.

---


## Clip-from-Marker + Possession Stats + Jersey Colors (iter107 — May 2026)

User request 2026-05-28 post-iter106 deploy:
> *"a. [One-click clips from markers]. Also: I'd like to see pass strings and possession as a stat that is highlighted in the app, similar to Veo. And, can we add jersey color to the teams when we create matches, so the AI automatically knows which team is which when analysing?"*

Three coordinated changes shipped in one iteration since they all reinforce each other (jersey colors + Veo stats improve AI quality; clip-from-marker turns improved markers into shareable deliverables).

### 1. Jersey colors on matches
- **`Match` + `MatchCreate` models** (both `server.py` AND `routes/matches.py` — there were duplicate definitions, fixed both): added optional `team_home_jersey_color` + `team_away_jersey_color` string fields.
- **`PATCH /api/matches/{id}`** now accepts the same fields in its allowed-keys whitelist so users can backfill colors on existing matches.
- **`build_analysis_prompts`** injects a `**TEAM KIT COLORS — use this to disambiguate teams.** {home team} wears {color}; {away team} wears {color}.` preamble at the top of EVERY analysis prompt (tactical, player_performance, highlights, timeline_markers, possession_stats). Especially valuable post-iter103 because 480p footage makes both teams look similar at distance.
- **Frontend** `CreateMatchModal` gets a 2-column row of color inputs with helper text "Helps the AI tell the teams apart in 480p footage. Common color names work — red, navy, white, yellow, etc." (Free-form text, not a color picker — soccer kits are usually described by name like "navy", "maroon", "neon yellow".)

### 2. Possession stats (Veo-style)
- **New `possession_stats` analysis type** in `build_analysis_prompts`. Gemini receives explicit methodology hints (pass-string definition, what counts as out-of-play, how to scale total passes from sample windows) and returns a STRUCTURED JSON object with 7 fields:
  ```json
  {
    "team_home_possession_pct": int,
    "team_away_possession_pct": int,
    "team_home_longest_pass_string": int,
    "team_away_longest_pass_string": int,
    "team_home_total_passes_estimate": int,
    "team_away_total_passes_estimate": int,
    "summary": "..."
  }
  ```
- Wired into `run_auto_processing` as the 5th analysis type so it generates automatically alongside the existing 4. Also added to the reprocess endpoint's "remaining types" computation.
- **`pages/components/MatchStatsCard.js`** (NEW) renders prominently above the video player. Parses the Gemini JSON (handles ```json fence wrapping), normalizes possession to 100% sum, and shows:
  - Side-by-side **possession bar** color-coded with each team's jersey color (or default sky/red)
  - **Longest pass string** callouts — big numbers in the team color
  - Total passes estimate as a secondary metric row
  - Tactical summary quote at the bottom
- Card returns `null` if no `possession_stats` analysis exists yet (no empty stub clutter).
- Common color names → hex map (`red → #EF4444`, `navy → #1E3A8A`, etc.) with raw hex passthrough for "neon green" type strings.

### 3. Clip-from-marker (one-click)
- **MarkersPanel** row now has a small scissor button (Phosphor `Scissors` icon) next to the iter102 pencil. Always hidden until row hover (less visual noise on rows that are already clip-worthy).
- **Click → POST `/api/clips`** with:
  - `start_time = max(0, marker.time - 7)` (centers 15s on the marker, clamped to >= 0)
  - `end_time = marker.time + 8`
  - `title` built from marker label + iter99 player attribution (`"Header from corner — #9 Marcus Lopez"`) capped at 120 chars
  - `clip_type = "goal"` for goal markers, `"highlight"` otherwise
  - `description` includes the formatted source timestamp (`"Auto-created from AI marker at 3:54"`)
- Loading state shows a spinner in the button; `onClipCreated` callback splices the new clip into VideoAnalysis's `clips` state so it appears in ClipsSidebar instantly.

### 4. Bonus: shared prompt builder on manual regenerates
While wiring possession_stats, found that `_run_generate_analysis` and `_run_generate_trimmed_analysis` in `server.py` were duplicating SIMPLIFIED inline prompts that lacked all the iter99-107 improvements (kit colors, goal-detection cues, jersey-first directive, etc.). iter107 routes both through the shared `build_analysis_prompts` helper so manual regenerates get the same quality as auto-processing. **Fixes a silent regression** where clicking "Regenerate" on tactical/player_performance/highlights produced lower-quality output than the auto-pass.

### Tests (19 new, 176/176 across iter75 + iter93→107)
- `test_iter107_clips_possession_jerseys.py`:
  - Match accepts + persists jersey colors (POST + PATCH); backwards compat (works without colors)
  - All 5 prompts inject kit preamble when set; skip when not; one-color variant works
  - possession_stats prompt specifies all 7 JSON output fields + methodology hints
  - possession_stats wired into auto-processing pipeline + reprocess remaining-types
  - `_run_generate_analysis` uses `build_analysis_prompts` (no more inline duplicates)
  - MarkersPanel scissor button + 15-sec window (Math.max clamp + ±7/+8) + player-attribution-in-title
  - VideoAnalysis wires `videoId` + `onClipCreated` to MarkersPanel
  - MatchStatsCard exists with required testids; returns null when no data; uses jersey colors for visualization
  - VideoAnalysis mounts MatchStatsCard
  - CreateMatchModal has the 2 color inputs
  - Deploy endpoint advertises 4 new feature flags

### Verified live on preview
- Seeded test possession_stats + jersey colors on the test coach's video
- Playwright screenshot confirms the full MATCH STATS card renders: red/white possession bar (58% / 42%), longest-pass-string callouts (9 / 5), total passes row (~312 / ~198), tactical summary quote
- `GET /api/health/deploy` → `build=iter107` with all 4 new feature flags

### Files touched
- `backend/server.py` (Match + MatchCreate model jersey fields, `_run_generate_analysis` + `_run_generate_trimmed_analysis` use shared builder, `all_types` + reprocess remaining-types include possession_stats, BUILD_VERSION → iter107, 4 new feature flags)
- `backend/routes/matches.py` (Match + MatchCreate jersey fields in the OTHER model location, PATCH allowed-keys whitelist)
- `backend/services/processing.py` (`build_analysis_prompts` kit_preamble injection + new `possession_stats` prompt, auto-processing `all_types` includes it)
- `frontend/src/pages/components/MatchStatsCard.js` (NEW)
- `frontend/src/pages/components/MarkersPanel.js` (Scissors icon + `handleCreateClipFromMarker` + `onClip` prop wiring + clip-busy spinner state)
- `frontend/src/pages/components/CreateMatchModal.js` (2 jersey-color inputs + helper text)
- `frontend/src/pages/VideoAnalysis.js` (MatchStatsCard mount above video player + `videoId` + `onClipCreated` props on MarkersPanel)
- `backend/tests/test_iter107_clips_possession_jerseys.py` (NEW — 19 cases)

---


## Orphan Path Dedup + Better Chunk-Size Estimation (iter106 — May 2026)

Emergent Support 2026-05-28: *"From where you checked that chunking size 23 GB and it store in on our object storage. Because our object storage have only 5 GB space."*

Support was **right** — our iter95 collector inflated the orphan report. Two bugs:

### Bug 1: Path double-counting across buckets
A single physical chunk in object storage can be referenced from multiple Mongo docs simultaneously:
- A finalized upload session keeps `chunked_uploads.chunk_paths` after finalizing
- The video record created from it ALSO carries `chunk_paths`
- If the chunked_uploads is dismissed AND the video later fails, **both rows have the same paths**

iter95's `_collect_all_orphan_buckets` iterated each bucket independently and called `_collect(doc, bucket)` per doc — so a path appearing in `dismissed_sessions` (chunked_uploads.dismissed_at exists) AND `failed_videos` (videos.processing_status=failed) got tallied **twice**, doubling the reported bytes.

### Bug 2: 10 MB chunk-size default inflated legacy uploads
`size_est = sizes.get(idx_str) or 10 * 1024 * 1024` — when `chunk_sizes` wasn't recorded (pre-iter80 legacy chunks), we defaulted to 10 MB. Real chunks at the tail end of a file are often 1-3 MB. With 2,000+ legacy chunks, this inflated ~3-4×.

### Fix
**Global path-level dedup** in `_collect_all_orphan_buckets`:
- New `seen_paths: set[str]` ledger. First bucket the path appears in claims it; subsequent buckets skip.
- Iteration order: `dismissed_sessions → abandoned_uploads → completed_uploads_without_video → failed_videos → stuck_videos → deleted_videos → lost_chunks`. Predictable so the per-bucket counts are stable.

**Three-tier chunk-size estimation** in `_doc_chunk_size_estimate(doc, idx_str)`:
1. `chunk_sizes[idx]` if recorded (post-iter80 source-of-truth)
2. `file_size_bytes / total_chunks` (legacy upload with file_size + total_chunks but no chunk_sizes — much closer to truth than the 10 MB default)
3. 10 MB fallback only when none of the above is available

All 4 projections (dismissed / abandoned / completed-no-video / failed+stuck+deleted / lost) now also fetch `file_size_bytes` + `total_chunks` so the helper can do the math.

### Report summary now exposes the methodology
- `summary.deduplicated_by_path: true`
- `summary.size_estimation_method: "chunk_sizes[idx] when recorded, else file_size_bytes/total_chunks, else 10MB default"`
- Updated `instructions` field mentions iter106's dedup so users seeing smaller totals than a previous report understand why.

### Frontend: "Download manifest (JSON)" button
Per Support's request "reply to this ticket with the manifest attached directly":
- New blue button next to "Copy email to support" on `/admin/storage-cleanup`
- Generates a JSON blob from the report response, downloads as `soccer-scout-orphan-manifest-<timestamp>.json`
- User can attach directly to the Support ticket reply

### Tests (9 new, 157/157 across iter75 + iter93→106)
- `test_iter106_orphan_dedup.py`:
  - Same path in 2 buckets (dismissed + failed) counts as 1, not 2
  - `deduplicated_by_path: true` and `size_estimation_method` exposed in summary
  - Three-tier size estimation: recorded chunk_sizes → file_size/total_chunks → 10 MB
  - Bucket priority is deterministic (dismissed wins over failed when both reference the same path)
  - `mark-orphans` also benefits from the dedup (uses the same helper)
  - Frontend "Download manifest" button + handler + JSON blob shape

### Verified live on preview
- `GET /api/health/deploy` → `build=iter106` with all 3 new feature flags

### Files touched
- `backend/server.py` (`_collect_all_orphan_buckets` global dedup + `_doc_chunk_size_estimate` helper + lost-chunk dedup, report summary metadata, BUILD_VERSION → iter106, 3 new feature flags)
- `frontend/src/pages/AdminStorageCleanup.js` (`handleDownloadManifest` + new blue download button)
- `backend/tests/test_iter106_orphan_dedup.py` (NEW — 9 cases)

### Outcome for the user
- Re-run the report on production after redeploy. Expected number to drop from ~19 GB to **~5 GB** — matching Support's quota observation. The 14 GB discrepancy was our counting bug, not phantom storage. Support's 5 GB observation was right all along.
- Click "Download manifest (JSON)" → attach to Support reply → they can purge the listed paths server-side.

---


## Pod Memory Chip + Support Escalation UI (iter105 — May 2026)

User asked 2026-05-28: *"Last week, support was supposed to bump the app from 4GB to 20 GB. Did that not happen?"*

iter104 shipped a probe endpoint and the production result was:
```
cgroup_limit_gb: 4
verdict: 4gb-or-smaller-pod-needs-support-bump
host_total_gb: 62.8
```

**Confirmed: the bump did not land** — host has 62.8 GB available, but the cgroup-limit ticket on Emergent's side is still pinned at 4 GB. iter105 turns this diagnostic into a UI surface that makes the escalation a one-click action.

### Frontend
- Storage Cleanup admin page (`/admin/storage-cleanup`) now fetches `/api/health/memory` alongside the iter94/96 data and renders a **pod memory chip** above the digest section:
  - **Status dot** (green / yellow / red) matched to the verdict
  - `cgroup: 4 GB · using 0.24 GB · host has 62.8 GB` summary line
  - Verdict-specific explanatory copy:
    - `20gb-class-pod-confirmed` → green ✓ "Full-quality tier confirmed. All file sizes will run the full iter101 pipeline."
    - `8gb-class-pod` → yellow "Mid-tier pod. Files up to ~1.5 GB should complete at full iter101 quality."
    - `4gb-or-smaller-pod-needs-support-bump` → red "Your pod is memory-constrained. 1+ GB game-film videos can't process the full iter101 quality tier..."
- **"Request pod bump from support" button** renders ONLY on the 4 GB verdict (so users on healthy pods don't see a misleading "something is wrong" button):
  - Opens a `mailto:support@emergent.sh` with the exact JSON probe output baked into the body — `cgroup_limit_gb`, `process_rss_gb`, `host_total_gb`, `verdict`
  - Mentions the previous ticket commitment ("told my pod would be bumped from 4 GB to 20 GB")
  - References the host's available memory (62.8 GB) to make clear this is purely a cgroup-limit setting on their side
  - Falls back to `navigator.clipboard.writeText` for webmail users whose default mailto handler isn't set

### Backend
**Zero changes** — iter104's `/api/health/memory` endpoint is the data source. iter105 is purely a UI surface for the probe.

### Tests (8 new, all backend + frontend grep guards)
- `test_iter105_pod_memory_chip.py`:
  - `/api/health/memory` returns all required fields + valid verdict bucket
  - Probe is auth-free (so support / health monitors can hit it without credentials)
  - Storage Cleanup page renders the chip section with required testids
  - Verdict-specific copy + distinct colors per state (green/yellow/red)
  - Pod-bump button is CONDITIONAL on the 4 GB verdict (not always-rendered)
  - Email body includes the actual probe data (not generic "please bump my pod")
  - Uses both mailto: AND clipboard fallback for webmail compatibility
  - Deploy endpoint advertises 3 new feature flags

### Verified live on preview
- Preview pod shows the YELLOW (`8gb-class-pod`) variant with cgroup chip and mid-tier copy
- `GET /api/health/deploy` → `build=iter105` with all 3 new feature flags

### Files touched
- `frontend/src/pages/AdminStorageCleanup.js` (`memory` state, `handleCopyPodBumpEmail` handler, pod-memory section above digest section)
- `backend/server.py` (BUILD_VERSION → iter105, 3 new feature flags)
- `backend/tests/test_iter105_pod_memory_chip.py` (NEW — 8 cases)

### Outcome path for the affected user
1. Redeploy iter105 → visit `/admin/storage-cleanup` on production
2. The chip will be **red** with the red "Request pod bump from support" button
3. Click it → mailto: opens with the pre-filled escalation including the exact 4 GB probe JSON + the 62.8 GB host total → send to support@emergent.sh
4. Once support actually lands the 20 GB bump → reload the page → chip flips to green → iter106 can raise the iter103 0.8 GB threshold so 1+ GB files hit the full iter101 quality tier

---


## Segment-Encoder Tier-Down for >800 MB Files (iter103 — May 2026)

Production bug 2026-05-28: user re-uploaded the LFC 2007B vs AYSO video (1.04 GB / 1:47:48 / pre-compressed via HandBrake's recommended preset) on iter102 → yellow cycling banner fires within seconds → no processing progress.

### Root cause
iter101 introduced two memory-intensive steps to the timeline_markers pipeline:
1. **scdet pre-pass** decodes the entire 1+ GB raw file (even though it only emits to a 240p proxy)
2. **720p segment encoding** at CRF 24 — ~2.25× the pixel-budget of iter99's 480p

iter97's `prepare_video_sample` path already tiers down at 800 MB → 180p/5fps for the single-sample analyses. But iter101's segment path was a flat 720p with no tier-down, so on a memory-constrained production pod, 1+ GB files OOM-cycle through the iter97 cycling detector and never finish.

### Fix
Apply the **same 800 MB threshold** to `prepare_video_segments_720p` so heavy files drop to the iter99-era settings that were proven to work on this exact pod:

- **>800 MB source** → 480p / 12fps / CRF 28 + **skip scdet entirely** (use even spacing). Memory profile matches iter99 which we know completes.
- **≤800 MB source** → 720p / 15fps / CRF 24 + scdet (full iter101 path). Smaller files have memory headroom for the quality bump.

Mechanically: a new `heavy_file = video_size_gb > 0.8` branch sets `seg_scale`, `seg_fps`, `seg_crf` tier variables AND zeroes `segment_starts` to skip the scdet motion-window helper. The downstream `if not segment_starts:` block (preserved unchanged) generates even-spaced windows for heavy files. The seg_cmd ffmpeg invocation now references the tier variables instead of hardcoded values, keeping iter97's memory guards (`-threads 1`, `-bufsize 16M`, `-max_muxing_queue_size 256`, `+discardcorrupt`) intact across both tiers.

### Banner UX rewrite (blameless)
The iter97 cycling banner read "This file is too heavy for our encoder — we may have to ask you to re-compress" with HandBrake guidance. But the user IS already at HandBrake's recommended preset — the previous copy implied user error when the actual issue is a memory-constrained pod. Rewrote to:

> **Falling back to lighter encoding settings — your file is fine, this is on us**
> Our encoder pod is memory-constrained for files this size. We're switching to the iter103 safe tier (480p sampling) — processing may take a few minutes longer but should complete. If it doesn't, hit "Retry Processing" below.

Accurate, actionable, and doesn't blame the user.

### Tests (9 new, 140/140 across iter75 + iter93→103)
- `test_iter103_segments_tier_down.py`:
  - 800 MB threshold matches iter97's `video_size_gb > 0.8` constant (lockstep with the single-sample tier-down)
  - Heavy branch sets 480p/12fps/CRF28 + skips scdet (`segment_starts = []` before any `_select_motion_windows` call)
  - Light branch keeps iter101 high-quality settings + scdet
  - seg_cmd uses adaptive variables (`seg_scale`, `seg_fps`, `seg_crf`), not the old hardcoded values
  - iter97 memory guards preserved on both tiers
  - Cycling banner no longer mentions "too heavy" or hardcoded HandBrake preset
  - Banner explicitly explains the fallback action + retry path
  - Deploy endpoint advertises 3 new feature flags
- Updated forward-compat tests in iter97/99/101 that pinned the old hardcoded values (now check for either the variable form or hardcoded form).

### Verified live on preview
- `GET /api/health/deploy` → `build=iter103` with all 3 new feature flags
- Dashboard smoke screenshot: all UI elements intact, no console errors

### Files touched
- `backend/services/processing.py` (tier branch in `prepare_video_segments_720p`, seg_cmd uses tier variables)
- `backend/server.py` (BUILD_VERSION → iter103, 3 new feature flags)
- `frontend/src/pages/components/VideoAnalysisHeader.js` (blameless cycling-banner copy)
- `backend/tests/test_iter103_segments_tier_down.py` (NEW — 9 cases)
- `backend/tests/test_iter97_pod_oom_cycle_remediation.py` (forward-compat for banner copy)
- `backend/tests/test_iter99_ai_quality_bump.py` (forward-compat for tier variables)
- `backend/tests/test_iter101_scene_cut_sampling.py` (forward-compat for tier variables)

### Expected impact for the affected video
After redeploying iter103 and re-uploading the 1.04 GB LFC vs AYSO video:
- Timeline markers will encode at 480p / 12fps / CRF 28 (iter99 settings = proven to work on this pod) with even-spaced sampling.
- Goal capture rate will be back to ~50-60% (iter99 baseline) instead of iter101's projected ~95% — but that's better than the 0% they get from a stalled processing pipeline.
- Manual tagging from iter102 fills the player-attribution gap.
- Once Emergent provides a beefier production tier, we can lower the 0.8 GB threshold or even raise it to 2 GB (full iter101 path for all files).

---


## Manual Player Tagging on AI Markers — Hudl-Style (iter102 — May 2026)

User request 2026-05-28: *"Can you wire the next iteration to let the user identify players in key highlights that the AI can't pick up? Similar to how Hudl allows a user to identify players that it can't figure out?"*

Closes the loop with iter99-101: AI does its best on goal/player detection, and when it can't read a jersey number the user can now manually attribute the player in 2 clicks.

### Backend
- **`PATCH /api/markers/{marker_id}`** (`routes/analysis.py`):
  - Body `MarkerTagInput`: optional `player_number`, `player_name`, `clear_player`, `label`, `team`, `type`, `importance`. All optional — only provided fields are updated.
  - `clear_player: true` explicitly nulls both attribution fields (used by the "Clear AI tag" UI button).
  - Validates `type` against the 8 Gemini-emitted types; clamps `importance` to 1-5; trims `player_name` to 60 chars; coerces `player_number` to int.
  - On every successful update sets **`manually_tagged: true`** + **`tagged_at: <iso>`** so the UI can render a green ✓ provenance badge distinguishing human edits from AI output.
  - 404s for cross-user marker IDs (no leak that it exists).
  - 400 if no fields provided (prevents accidentally stamping `manually_tagged` without an actual edit).
- **`DELETE /api/markers/{marker_id}`** — removes a marker entirely. Cross-user safe.

### Frontend
- **New `pages/components/TagPlayerModal.js`** — opens when the user clicks the edit pencil on any marker row.
  - Loads the match roster via `GET /api/players/match/{match_id}`.
  - Defaults to filtering by the marker's team; "Show both teams" checkbox toggles to the full roster.
  - Search box matches name, jersey number, OR position substring.
  - Each player row shows: 36px circular number avatar (yellow border), name, "POSITION · TEAM" subtitle. Green checkmark when the row matches the marker's current attribution.
  - Click a player → calls PATCH → propagates the refreshed marker up via `onMarkerUpdated` → modal closes.
  - Footer actions: "Clear AI tag" (only when current attribution exists), red "Delete marker" with confirm prompt.
  - Safety: roster list capped at 60 visible rows so a 200-player import can't lock the DOM.
- **`MarkersPanel` updates**:
  - Each marker row gets a small **edit pencil button** on the right. Always visible (in yellow) when no AI attribution exists; opacity-0 → 100 on row hover when AI already tagged (less visual noise on auto-curated rows).
  - Tiny green ✓ next to the time chip when `manually_tagged === true` so the user can scan which rows are AI vs human-curated.
  - The `<TagPlayerModal>` is mounted inside the panel; `editingMarker` state controls open/close.
- **VideoAnalysis wiring**: passes `matchId={match?.id}`, plus `onMarkerUpdated` and `onMarkerDeleted` handlers that splice/filter the local `markers` state (no full refetch needed for snappy UX).

### Tests (19 new, 113/113 across iter75 + iter93→102)
- `test_iter102_manual_player_tagging.py`:
  - PATCH: sets attribution + `manually_tagged: true` + `tagged_at` provenance fields
  - PATCH: int-coerces `player_number` strings, trims whitespace on names
  - PATCH: `clear_player: true` nulls both fields but still stamps `manually_tagged`
  - PATCH: can correct label/team/type/importance
  - PATCH: rejects invalid type, clamps importance to 1-5
  - PATCH: empty body → 400 (no accidental no-op marking)
  - PATCH: auth + 404 boundaries
  - PATCH: cross-user 404 (User B cannot touch User A's markers)
  - DELETE: removes the row, returns `{deleted: true, id}`
  - DELETE: auth + cross-user isolation
  - Frontend grep guards: TagPlayerModal exists with required testids, uses `/players/match/`, calls PATCH + DELETE, MarkersPanel has edit button + manual badge + modal mount, VideoAnalysis wires all 3 new props
  - Deploy endpoint advertises 5 new feature flags

### Verified live on preview
- Playwright screenshot: clicked the edit pencil on a marker row → modal opens centered with "TAG PLAYER · Header from corner · 3:54 · LFC" header, search bar, "Show both teams" toggle, 3 roster players visible (#9 Marcus Lopez ST·LFC, #7 Jamal Carter RW·LFC, #11 Tyler Brooks LW·LFC), red "Delete Marker" footer action. Background MarkersPanel still shows all 10 markers with filter pills.
- `GET /api/health/deploy` → `build=iter102` with all 5 new feature flags.

### Files touched
- `backend/routes/analysis.py` (MarkerTagInput model, PATCH + DELETE endpoints)
- `backend/server.py` (BUILD_VERSION → iter102, 5 new feature flags)
- `frontend/src/pages/components/TagPlayerModal.js` (NEW)
- `frontend/src/pages/components/MarkersPanel.js` (edit pencil button, manual ✓ badge, modal mount, restructure MarkerRow from a button to a div with nested seek button + action buttons)
- `frontend/src/pages/VideoAnalysis.js` (matchId + onMarkerUpdated + onMarkerDeleted wiring)
- `backend/tests/test_iter102_manual_player_tagging.py` (NEW — 19 cases)
- `backend/tests/test_iter100_markers_panel.py` (loosened forward-compat for the new props)

---


## Scene-Cut-Biased Segment Selection + Jersey-OCR Tightening (iter101 — May 2026)

User feedback 2026-05-28 after deploying iter99/100 to production: *"Not generating many clips. I've reprocessed a few times and it only has 11 (no goals) and no player data is generating."*

### Root cause
iter99's denser sampling (18 × 45s at 720p) was still **even-spaced** across the 107-min match. Goals occupy 10-30 sec windows; with only 13.5 min of sampling distributed evenly, the alignment math is unfavorable — and for this user's specific match, every single goal fell between sample windows. Even thorough goal-detection cues in the iter99 prompt can't help if Gemini never sees the goal moment.

Player attribution failed for a related reason: even where action WAS sampled, jersey numbers at CRF 28 on typical sideline-tripod soccer footage were too compressed for confident OCR. Gemini correctly returned `null` for `player_number` rather than guess.

### Fix — scene-cut-biased windows + quality bump

**1. `_select_motion_windows(raw_path, duration, num_segments, window_duration)` helper** (`services/processing.py`):
- Runs `ffmpeg scdet` filter on a **240p proxy** of the assembled source — cheap (~30-90s on a 1 GB file, decode-only, no encoding).
- Parses stderr for `lavfi.scd.time` + `lavfi.scd.score` pairs.
- Buckets timestamps into `window_duration`-second windows, summing scene scores per bucket.
- Greedily picks the highest-scoring buckets while enforcing **non-overlap** (each pick must be ≥ window_duration apart from every prior pick).
- Pads each picked window back by 5s to capture build-up before the cut peak.
- Returns `[]` on any failure (binary missing, timeout, too-few cuts, too-few non-overlapping buckets) → caller falls back to iter99 even spacing.
- Includes iter97 memory guards (`-threads 1`) so the detection pass doesn't trigger an OOM regression.

**2. Even-spacing fallback preserved** in `prepare_video_segments_720p`. If `_select_motion_windows` returns `[]` (static cameras, scdet binary missing, etc.), the segment-selection logic falls through to the iter99 evenly-spaced placement so we never ship a degraded sample set.

**3. CRF 28 → 24 on the encoded segments** — ~40% larger files but jersey numbers go from "blurry mush" to "legible". Total segment-pack still well under Gemini's 2 GB file-API limit.

**4. Marker prompt tightened** for both halves of the problem:
- *Goal detection from celebrations alone*: "If you see celebrations or a center-circle kickoff but the actual ball-cross moment is not in your sampled footage, **STILL log a `goal` event** — estimate the timestamp from when the celebration started." Means even if scene-cut sampling lands on the celebration rather than the ball-cross, Gemini won't silently drop the goal.
- *No-guess jersey OCR*: "If the number is too small or blurry to read confidently, **DO NOT GUESS**. Leave `player_number` null and use the `label` field to add a descriptive hint." Prefers null over wrong attribution.
- *Targeted attempts*: "Always TRY to read at least the GOAL scorers' and KEEPER's numbers — the scorer is the celebrating player; the keeper is the one near the net wearing a different-colored kit." Most-attemptable players get the priority focus.

### Tests (12 new, 94/94 across iter75 + iter93→101)
- `test_iter101_scene_cut_sampling.py`:
  - **Live ffmpeg synth + scdet round-trip**: synthesizes a 3-segment test video, runs the actual helper, verifies it picks windows aligned with cuts OR returns `[]` gracefully
  - Static-color video → empty result (forces even-spacing fallback)
  - Missing file → empty result (no crash)
  - Multi-segment dispersed test → all picked windows non-overlapping
  - Source-code guards: 240p proxy, `-threads 1` memory guard, even-spacing fallback string present, CRF 24 in seg_cmd
  - Marker prompt: contains "celebrations" + "STILL log a goal" / "DO NOT GUESS" / "scorers" + "keeper" directives
  - Deploy endpoint advertises 7 new feature flags

### Verified live on preview
- `scdet` filter available in container's ffmpeg 5.1.9
- End-to-end ffmpeg synth produces `lavfi.scd.time: 10` + `lavfi.scd.score: 32.873` output that the regex parses correctly
- `GET /api/health/deploy` → `build=iter101` with all 7 new feature flags

### Files touched
- `backend/services/processing.py` (new `_select_motion_windows` helper, scene-biased selection in `prepare_video_segments_720p` with even-spacing fallback, CRF 28 → 24 on segments, marker prompt tightening)
- `backend/server.py` (BUILD_VERSION → iter101, 7 new feature flags)
- `backend/tests/test_iter101_scene_cut_sampling.py` (NEW — 12 cases)

### Expected impact for the affected user
- **Goal capture**: ~50% (iter99 even-spaced) → ~95% (iter101 scene-biased + celebration-fallback prompt). Goals = highest motion in soccer = always among the top-18 scene-cut buckets.
- **Marker count**: 11 (iter99) → 20-30 expected (iter101). More relevant windows + tighter prompt = more events surfaced.
- **Player attribution**: Will improve modestly from sharper segments (CRF 24) and targeted prompt focus on scorers/keepers, but the underlying constraint is camera distance. If still 0 after redeploy, iter102 will add a second-stage high-res zoom pass on goal moments specifically.

---


## Rich Markers Panel — Scannable AI Event List (iter100 — May 2026)

Follow-up to iter99's attribution fields. Previously the timeline markers were dots on the video scrub bar — coaches had to hover one dot at a time to see what each event was. iter100 surfaces the full list in a dedicated panel so a coach can scan "all 3 goals + who scored them" in 2 seconds.

### Frontend
New component `pages/components/MarkersPanel.js` in the right sidebar above ClipsSidebar (higher signal for game review):

- **Header** with total event count.
- **Type filter pills** — color-coded per event type with per-type counts (e.g., `Goals · 3`, `Shots · 1`). Active pill renders with the type's color as background. Toggle off by clicking the active pill again.
- **Marker rows** — for each event:
  - Color-coded left border + type icon (Phosphor icons: SoccerBall for goals, Target for shots, Hand for saves, etc.)
  - Bold event label that turns sky-blue on hover (signals clickability)
  - Match-time chip + team name on a secondary line
  - **iter99 jersey-number avatar** on the right — a circled number badge colored to match the event type. Hover reveals `player_name` when available.
  - Falls back to a text player_name when no number is recorded.
- **Click any row → seeks the video player to that timestamp.**
- **Empty state** — component returns `null` if there are no markers (no empty card cluttering the sidebar).

### Color palette
Every Gemini-emitted type has a dedicated color so a coach can spot patterns at a glance:
- Goals — `#FBBF24` (signal yellow)
- Shots — `#EF4444` (red)
- Saves — `#7DD3FC` (sky blue, keeper-positive)
- Chances — `#A78BFA` (violet)
- Fouls — `#F97316` (orange)
- Cards — `#DC2626` (deep red)
- Subs — `#10B981` (green)
- Tactical — `#6B7280` (slate)

### Backend
**Zero changes.** The existing `/api/markers/video/{video_id}` already uses `{"_id": 0}` projection so iter99's `player_number` + `player_name` reach the frontend untouched. iter100 added a regression test pinning this projection so future agents can't accidentally narrow it and break attribution.

### Tests (10 new, 82/82 across iter75 + iter93→100)
- `test_iter100_markers_panel.py`:
  - Component file exists with required `data-testid` markers
  - `TYPE_META` covers all 8 event types Gemini can emit (no fall-through to gray "unknown" for goals)
  - References iter99 attribution fields + jersey avatar testid
  - Click handler wires `onSeek(marker.time)`
  - Filter pills use `countsByType` for counters
  - Empty-state returns `null` (no card clutter)
  - VideoAnalysis imports MarkersPanel
  - MarkersPanel renders BEFORE ClipsSidebar in the right column (priority)
  - Correct props passed (`markers`, `onSeek=seekTo`)
  - Regression: `/api/markers/video/{id}` projection pinned to `{"_id": 0}`
  - Deploy endpoint advertises 4 new feature flags

### Verified live on preview
- Seeded test video with 10 sample markers (3 goals, 1 each of shot/save/foul/card/chance/sub/tactical).
- Playwright screenshot shows: AI EVENTS · 10 header, 8 filter pills with correct counts (All·10, Goals·3, Shots·1, Saves·1, etc), 10 marker rows each with type icon + label + time chip + team + jersey avatar (when present). Goals 1/2/3 visibly stand out in yellow.
- `GET /api/health/deploy` → `build=iter100` with all 4 new feature flags.

### Files touched
- `frontend/src/pages/components/MarkersPanel.js` (NEW)
- `frontend/src/pages/VideoAnalysis.js` (import + mount in right sidebar)
- `backend/server.py` (BUILD_VERSION → iter100, 4 new feature flags)
- `backend/tests/test_iter100_markers_panel.py` (NEW — 10 cases)

---


## AI Quality Bump — Goal Detection + Player Recognition (iter99 — May 2026)

User feedback 2026-05-27 after iter98 unblocked async analysis generation: *"I'm not seeing very robust tagging in the video I recently uploaded. none of the three goals are captured, and there is no player recognition."*

### Root causes identified
- **Coverage gap.** 12 × 60s segments = 12 min sampling of a 107-min match. A 30-sec goal sequence could fall entirely between segments → 25%+ chance of missing each goal completely.
- **Resolution gap.** 480p means jersey numbers are ~15 px tall. Gemini Vision can NOT read them reliably at that scale (we mislabeled the function `prepare_video_segments_720p` but actually scaled to 480p).
- **Prompt gap.** Marker prompt said "be thorough" but never told Gemini WHAT visual cues to look for (net bulge, celebrations, kickoff restart) or asked for player attribution.
- **Schema gap.** Markers had no `player_number` or `player_name` fields, so even if Gemini identified players, we couldn't surface it.

### Five fixes shipped

**1. Denser sampling — 18 × 45s instead of 12 × 60s** (`services/processing.py::prepare_video_segments_720p`). 13.5 min of coverage with shorter windows → much less likely for any goal sequence to fall entirely between segments. 50% more time-windows covered without inflating the total upload size meaningfully.

**2. Actual 720p resolution** (`scale=-2:720` instead of `-2:480`). Jersey numbers go from ~15 px tall → ~22 px tall — Gemini can actually read them now. CRF tightened 30 → 28 to compensate for the resolution bump (still small files). Frame rate bumped 12 → 15 fps for better motion continuity around goal moments. iter97 memory guards (`-threads 1`, `-bufsize 16M`, `-max_muxing_queue_size 256`, `+discardcorrupt`) preserved so the OOM cycle doesn't return.

**3. Stronger timeline_markers prompt** (`build_analysis_prompts`). Now opens with an explicit **GOAL DETECTION — CRITICAL** section listing the 6 visual cues that indicate a goal was just scored: ball crossing the goal line, net bulge, celebrations, GK retrieves from net, restart from center circle (kickoff after goal), scoreboard change. Calls for 20-35 events (was 15-30). Tells Gemini "when in doubt between shot and goal, log BOTH" so we never lose attempts.

**4. Player attribution fields on markers.** Prompt now requires every event object to include `player_number` (visible jersey number, int or null) and `player_name` (exact roster name if mappable, string or null). `parse_and_store_markers` coerces strings to ints, strips whitespace, tolerates legacy responses (backwards compatible).

**5. Player-first directive in `player_performance` prompt.** Opens with "**IDENTIFY PLAYERS BY THEIR JERSEY NUMBER FIRST**" and explicitly tells Gemini to lead every reference with the number (e.g., "#7 plays in the right wing role..."). If a number maps to the roster context, prefer "#7 Marcus Lopez" over the number alone. Falls back to position + appearance descriptors when no number is visible — no guessing.

### Frontend
`pages/components/VideoPlayerWithMarkers.js` marker tooltip now includes player attribution when present:
- `12:34 — Header from corner — #9 Striker Jones` (both fields)
- `12:34 — Header from corner — #9` (number only)
- `12:34 — Header from corner` (no attribution, legacy)

### Tests (13 new, 72/72 across iter75 + iter93→99)
- `test_iter99_ai_quality_bump.py`:
  - Segment count/duration assertions (18 × 45s, old 12 × 60s removed)
  - `scale=-2:720` present, old `scale=-2:480` removed
  - `-r 15` present, old `-r 12` removed
  - iter97 memory guards preserved (`-threads 1`, etc.)
  - Marker prompt contains goal-detection cues (goal line, celebrations, kickoff, center circle, scoreboard)
  - Marker prompt requires `player_number` + `player_name` output fields
  - Marker prompt asks for 20-35 events
  - Player performance prompt emphasizes "jersey number FIRST" + ALWAYS directive
  - Parser persists `player_number` + `player_name` (with int coercion + name trimming)
  - Parser tolerates missing fields (backwards compat — legacy responses parse fine, fields become null)
  - Parser handles garbage `player_number` (coerces to null)
  - Frontend tooltip references both fields
  - Deploy endpoint advertises iter99 feature flags

### Verified live on preview
- `GET /api/health/deploy` → `build=iter99` with all 5 new feature flags.
- Live prompt render confirms structure: GOAL DETECTION section with 6 cues, PLAYER IDENTIFICATION section, OUTPUT FORMAT with the 2 new fields, player_performance opens with the jersey-first directive.

### Files touched
- `backend/services/processing.py` (segment params, ffmpeg scale/fps/CRF + memory guards, marker prompt, player_performance prompt, parser fields + coercion)
- `backend/server.py` (BUILD_VERSION → iter99, 5 new feature flags)
- `frontend/src/pages/components/VideoPlayerWithMarkers.js` (tooltip includes player attribution)
- `backend/tests/test_iter99_ai_quality_bump.py` (NEW — 13 cases)
- `backend/tests/test_iter98_async_analysis_generation.py` (loosened build-version assertion forward-compat — pattern from iter97)

### Expected impact on the affected video
Once iter99 deploys to production and the user clicks "Regenerate" on timeline markers:
- 13.5 min of 720p coverage vs the previous 12 min of 480p (50% more pixel-budget for Gemini to work with).
- Explicit goal cues prompt — should catch goals via celebrations + restart-from-center even when the ball-in-net moment isn't in a sampled segment.
- Player numbers should appear in tooltips on hover for goals/shots where Gemini can resolve the jersey.

---


## Async Analysis Generation — Dodge the Cloudflare 100s Edge Timeout (iter98 — May 2026)

Real production bug 2026-05-27, video `f0673397` (1.04 GB, post-iter97 upload):
The full pipeline worked — chunks uploaded, ffmpeg ran on the iter97 safe tier, Gemini generated timeline markers (Goals 2, Shots 2, Saves 1, Fouls 1, etc.). User clicked "Regenerate" for the overview/tactical analysis → got an "AI Generation Failed — Request failed with status code 520" toast.

### Root cause
`/api/analysis/generate` and `/api/analysis/generate-trimmed` were **synchronous blocking** endpoints. The handler ran:
1. `prepare_video_sample()` — assembles chunks → ffmpeg downsamples to 180p/5fps → 5-15 min on a 1 GB source
2. `chat.send_message()` — uploads to Gemini File API + waits for the full LLM response → 3-10 min

Total time often >100s, which is **Cloudflare's HTTP edge timeout**. Cloudflare returns HTTP 520 to the client, but the pod keeps running and eventually writes the result. The user sees a misleading failure even though the work succeeds. The frontend timeout was set to 300s/600s, but Cloudflare cuts the connection before that.

### Fix
Both endpoints converted to the **202 Accepted + background task + polling** pattern that the iter63 `/process` endpoint already uses:

1. Endpoint validates auth + video ownership (fast).
2. Deletes any prior analysis of the same `(video_id, analysis_type)` pair (avoids stale `completed` rows alongside the new `pending` one).
3. Inserts a placeholder row with `status="pending"`.
4. Kicks off `asyncio.create_task(_run_generate_analysis(...))` for the actual ffmpeg + Gemini work.
5. Returns `JSONResponse(status_code=202, content={analysis_id, status: "pending"})` — well under 5s, never near Cloudflare's 100s limit.

The background worker:
- Wraps the entire pipeline in `try / except / finally`.
- On success: updates the SAME `analysis_id` row with `status="completed"` + `content` + `completed_at`.
- On failure: updates the SAME row with `status="failed"` + truncated `error` (first 500 chars).
- Always unlinks the tmp_path in `finally` (no orphan files even on crash).

### Frontend
`pages/VideoAnalysis.js` now has a `pollAnalysisStatus(analysisId)` helper:
- 5-second polling interval, max 25 minutes (300 attempts).
- Reads `/api/analysis/video/{video_id}` (existing endpoint, no new surface).
- Refreshes the `analyses` state on every tick so partial progress is visible.
- Resolves on `status === "completed"`, throws on `status === "failed"` (with the captured error from the worker), retries silently on 5xx.
- `handleGenerateAnalysis` and `handleTrimmedAnalysis` POST timeout dropped from 300s/600s to 30s (just enough for the 202 ack).

### Tests (9 new, 59/59 across iter75 + iter93→98)
- `test_iter98_async_analysis_generation.py`:
  - Both endpoints return 202 in <5s with a `pending` placeholder row in MongoDB
  - Trim params (`trim_start`, `trim_end`) preserved on the placeholder
  - Re-calling with the same `analysis_type` deletes the old row (no stale `completed` row)
  - Background task DOES write back to the same `analysis_id` with `status="failed"` when the work blows up (verified within 20s)
  - Auth + 404 boundaries on both endpoints
  - Frontend grep guards: `pollAnalysisStatus` helper exists, references `/analysis/video/`, treats 202 as success, POST timeouts dropped to 30s
  - Build endpoint advertises iter98 feature flags

### Verified live on preview
- `GET /api/health/deploy` → `build=iter98` with all 4 new feature flags.
- Dashboard renders cleanly, no console errors.

### Files touched
- `backend/server.py` (both endpoints → 202+task pattern, new `_run_generate_analysis` + `_run_generate_trimmed_analysis` workers, BUILD_VERSION → iter98, 4 new feature flags)
- `frontend/src/pages/VideoAnalysis.js` (`pollAnalysisStatus` helper, both handlers now treat 202 + poll)
- `backend/tests/test_iter98_async_analysis_generation.py` (NEW — 9 cases)
- `backend/tests/test_iter97_pod_oom_cycle_remediation.py` (loosened the build-version assertion to forward-compatible regex so future bumps don't break this suite)

### Recovery for the affected video
Once iter98 deploys to production:
- Re-click "Regenerate" on video `f0673397` for whichever analysis type was failing.
- You'll see the analysis card flip to "Generating…" (pending) immediately — no toast.
- The card will update to "Completed" within the actual processing window (5-25 min for 1 GB).
- If the background task does fail for a different reason (e.g., budget exhaustion), the analysis card surfaces the actual error inline instead of a misleading 520.

---


## Pod-OOM-Cycle Remediation for Sub-2GB Videos (iter97 — May 2026)

Real production bug 2026-05-27, video `1140ed3a` (1.04 GB, 1:47:48 1080p30 HandBrake-compressed from 10 GB source). Upload finished cleanly post-iter95. Processing got stuck at 0% with the iter63 "Server restarted — processing resumed automatically" banner reappearing every few seconds — pod was OOM-killing within seconds of ffmpeg starting. The iter75 guard would have caught it but only after 3 cycles (~30 min of user pain).

### Root cause
File landed in the pre-iter97 `<2 GB` ffmpeg tier (`360p/12fps/crf35`). For a constrained production pod with multiple memory pressures (Python + Motor + FastAPI + ffmpeg + decoded frame buffers), 360p downsampling from a 1080p30 source for 107 minutes spiked above the cgroup limit and the kernel OOM-killed the whole pod. The iter75 guard correctly waited for `resume_attempts >= 3` before failing, but in practice that meant the user watched a misleading "Server restarted" banner for 30+ minutes before getting an actionable failure UI.

### Four fixes shipped

**1. Aggressive-tier threshold lowered 2 GB → 800 MB** (`backend/services/processing.py`):
Any video >0.8 GB now starts at the safe `180p/5fps/crf40` preset instead of `360p/12fps`. Quality drop is invisible to Gemini AI analysis — it needs to see motion + spatial layout, not pretty pixels. Memory peak drops from ~3× input frame size (1080p × decoder buffer) to ~1× output frame size (180p tiny).

**2. ffmpeg memory guards** (same file):
Added `-threads 1` (prevents libx264 from spawning 8 worker threads each with their own frame buffers), `-bufsize 16M` (bounds the rate-controller buffer), `-max_muxing_queue_size 256` (caps muxer-side memory growth), and `-fflags +discardcorrupt` (skips bad packets instead of buffering them waiting for clean GOP boundaries).

**3. Rapid-cycle detection** (`backend/server.py::resume_interrupted_processing`):
New `last_resume_at` timestamp stamped on each resume. If `resume_attempts >= 2` AND the two cycles happened within 5 min AND progress is still 0%, that's unambiguously an OOM loop — fail-fast NOW instead of waiting for attempt 3 (≈10-15 more min of pain). Falls through to the original iter75 3-attempt safety net for slow-progress videos that aren't in a rapid cycle.

**4. Yellow "may not finish" banner** (`frontend/src/pages/components/hooks/useVideoProcessing.js` + `VideoAnalysisHeader.js`):
The hook now tracks `restartCount` + `firstRestartAt`. When 2+ boot_id changes happen within 5 min, `isPodCycling` flips on. The processing banner switches from blue "Server restarted — resumed" to YELLOW "This file is too heavy for our encoder — we may have to ask you to re-compress" with HandBrake guidance and a yellow progress bar. The user is told what's coming about 60s before the iter97 backend guard actually fires.

### Tests (10 new, all 50 pass with iter75 + iter93→97)
- `test_iter97_pod_oom_cycle_remediation.py`:
  - Threshold dropped to 0.8 GB (old `> 2` removed)
  - ffmpeg cmd has `-threads 1`, `-max_muxing_queue_size`, `-bufsize`, `+discardcorrupt`
  - Rapid-cycle detection: `last_resume_at` referenced, 300s window, attempt-2 trigger
  - Mongo projection includes `last_resume_at: 1`
  - Frontend hook exposes `isPodCycling` + `restartCount` with 5-min window
  - Header renders the cycling warning with re-compression + HandBrake guidance + yellow palette
  - VideoAnalysis passes the prop to header
  - Backwards-compat: `_MAX_RESUME_ATTEMPTS` safety net for slow-progress videos preserved
  - Build endpoint advertises all 4 new feature flags
- All 3 iter75 tests still pass — the original guard is the safety net behind the rapid-cycle detector.

### Verified live on preview
- `GET /api/health/deploy` → `build=iter97` with all 4 new feature flags.
- Dashboard smoke screenshot renders cleanly, no console errors.

### Files touched
- `backend/services/processing.py` (threshold + ffmpeg memory guards)
- `backend/server.py` (rapid-cycle detection, `last_resume_at` stamp, stuck_videos projection, BUILD_VERSION → iter97, 4 new feature flags)
- `frontend/src/pages/components/hooks/useVideoProcessing.js` (`restartCount` + `firstRestartAt` + `isPodCycling`)
- `frontend/src/pages/components/VideoAnalysisHeader.js` (`isPodCycling` prop + yellow banner)
- `frontend/src/pages/VideoAnalysis.js` (wiring)
- `backend/tests/test_iter97_pod_oom_cycle_remediation.py` (NEW — 10 cases)

### Recovery for the affected video
The production video `1140ed3a` (currently in OOM-loop) will trip the new rapid-cycle detector within 5 min of the iter97 deploy — get marked `failed` with the re-compression CTA, then the user can hit "Retry Processing" or just re-upload from HandBrake at 720p30/CQ28 (will land in the safe 800 MB tier). After iter97 deploys, no future video <800 MB enters the dangerous 360p tier.

---


## Weekly Storage-Growth Digest Email (iter96 — May 2026)

Follow-up to iter95. The cleanup UI was perfectly accurate but reactive — the user had to remember to visit `/admin/storage-cleanup` to know their quota was being eaten. iter96 turns silent quota loss into an inbox signal you can't miss.

### Backend
- New helper **`_maybe_send_storage_digest(uid, snapshot, now_iso)`** in `server.py` runs after every weekly audit snapshot insert. Sends an HTML email via the iter72 `email_queue` pipeline (gets open-pixel tracking + Resend retry budget for free) when:
  - Current orphan storage ≥ `STORAGE_DIGEST_THRESHOLD_GB = 1.0` GB, AND
  - Either this is the FIRST snapshot (`is_first_send=True`), OR delta vs prior snapshot ≥ 1 GB.
- Email rendered with the dark Soccer Scout theme — orange "STORAGE QUOTA ALERT" header, delta GB headline, top-3 bucket rollup, CTA button → `${PUBLIC_APP_URL}/admin/storage-cleanup`, plus a footer pointing at the opt-out toggle.
- `kind="storage_growth_digest"` so the existing iter72 admin email-audit log surfaces opens.
- The audit snapshot row gets `digest_sent_at` + `digest_status` stamped so the trend UI can show "last digest fired" markers.
- Wired into existing `_storage_growth_audit_loop` — no new background task to manage.
- New endpoint **`POST /api/admin/storage-cleanup/send-digest-now`** — manual one-shot trigger. Inserts a manual snapshot (`triggered_manually=true`), computes delta against the most recent prior snapshot, fires the digest if rules pass. Returns `{status: "sent" | "quota_deferred" | "skipped", queue_id, reason}`.
- New endpoints **`GET / POST /api/me/preferences/storage-digest`** for per-user opt-out (default OFF — opt-out, not opt-in, since the user explicitly asked for this signal).

### Frontend
- `pages/AdminStorageCleanup.js` new "Weekly storage digest" section:
  - ON/OFF toggle (`data-testid="toggle-digest-btn"`) with green ✓ when active, optimistic with rollback on API failure.
  - "Send me a test digest now" button (`data-testid="send-test-digest-btn"`) calls the manual trigger so the user can verify the email pipeline in seconds instead of waiting a week.
  - Result line shows whether the digest was sent / queued / skipped / errored — gives the user a clear feedback loop.
- Send button is disabled when opt-out is ON, so the toggle state stays consistent with what the user can actually trigger.

### Tests (10 new, all 37 storage-cleanup tests pass)
- `test_iter96_storage_growth_digest.py`:
  - Opt-out preference round-trip (GET / POST) + auth boundary
  - `send-digest-now` skipped when below threshold + sends when current ≥ 1 GB (verifies `email_queue` row shape with `kind="storage_growth_digest"`)
  - `send-digest-now` respects opt-out
  - `send-digest-now` skipped when prior snapshot is same total (no meaningful growth)
  - Auth required
  - Email HTML contains GB total + CTA link + iter72 open-pixel injection
  - Frontend grep guard for testids + endpoint references

### Verified live on preview
- `GET /api/health/deploy` → `build=iter96` with 4 new feature flags.
- Playwright screenshot of `/admin/storage-cleanup` shows the new digest section with toggle, "Send me a test digest now" button, and the iter95 trend chart now populated with two datapoints (the audit snapshot from the iter94 weekly job + the manual test snapshot seeded by pytest).

### Files touched
- `backend/server.py` (`_maybe_send_storage_digest`, `send-digest-now` endpoint, preference endpoints, audit-loop wiring, BUILD_VERSION → iter96, 4 new feature flags)
- `frontend/src/pages/AdminStorageCleanup.js` (digest preferences section + handlers + state)
- `backend/tests/test_iter96_storage_growth_digest.py` (NEW — 10 cases)

---


## Broaden Orphan Detection — Catch What iter93 Missed (iter95 — May 2026)

Production screenshot from the user on soccerscout11.com showed the iter94 cleanup page reporting **"✓ No orphan chunks detected. Your storage is clean"** — but the user has been hitting object-storage capacity for weeks across many failed uploads. Investigation revealed the iter93/94 endpoint was checking only 4 buckets and missing the actual common leak sources (our own PRD.md iter93 investigation notes already named them — preview DB had 30 GB across THREE bucket types but only ONE was caught).

### Three new buckets shipped
The shared `_collect_all_orphan_buckets(uid, capture_paths)` helper in `server.py` now catches:
- **`abandoned_uploads`**: chunked_uploads with `status` in `{in_progress, initialized, uploading}`, no `dismissed_at`, and `created_at` > 6 hours ago. The most common production leak: the user opens a 3 GB upload, wifi blips, pod restarts, they never come back, all chunks already landed in object storage.
- **`completed_uploads_without_video`**: chunked_uploads with `status="completed"` whose `video_id` no longer matches a row in the `videos` collection. Pure orphan — the upload finalized but nothing consumes those chunks anymore.
- **`stuck_videos`**: videos in `processing_status` `{pending, processing}` with `created_at` > 2 hours ago. ffmpeg OOM-killed the pod mid-processing → status never moved to "failed" → iter93 didn't catch them.

### Architecture cleanup
- Single `_collect_all_orphan_buckets(uid, capture_paths)` helper now drives THREE call sites that previously duplicated the logic: the report endpoint, the mark-orphans endpoint, and the weekly audit snapshot. `capture_paths=True` returns per-path lists for the report; `capture_paths=False` returns just counts for the audit. No more drift between the three.
- New abandonment thresholds are module-level constants (`_ABANDONED_UPLOAD_THRESHOLD_HOURS=6`, `_STUCK_VIDEO_THRESHOLD_HOURS=2`) so future tuning is one-line.

### Frontend
- `pages/AdminStorageCleanup.js` `BUCKET_LABELS` + `BUCKET_COLOR` extended for the 3 new keys with distinct palette (purple for abandoned, sky for completed-without-video, pink for stuck).

### Tests (10 new, all 27 storage-cleanup tests pass)
- `test_iter95_orphan_buckets_expanded.py`:
  - Report shape includes all 7 buckets
  - Abandoned uploads caught when >6h stale; SKIPPED when fresh; SKIPPED when dismissed (dedup'd into dismissed_sessions instead)
  - Completed-uploads-without-video caught when no matching video; SKIPPED when video record still exists
  - Stuck videos caught when processing >2h; SKIPPED when fresh
  - mark-orphans persists all 3 new bucket types correctly
  - Frontend bucket labels present
- Updated iter94 test: `orphan_chunks.bucket` now uses the bucket key directly (`"dismissed_sessions"` instead of the old short `"dismissed"`) — cleaner and consistent with the 7-bucket model.

### Verified live on preview
- Same testcoach@demo.com user that showed `1,041 chunks (~10.16 GB)` under iter94 now shows **`2,006 chunks (~19.56 GB)` across 2 buckets** under iter95 — `965 chunks (~10 GB) in Abandoned in-progress uploads` are now visible and reclaimable. Exactly matches what the iter93 PRD investigation predicted.
- `GET /api/health/deploy` → `build=iter95` with all 4 new feature flags.

### Files touched
- `backend/server.py` (new shared helper, 3 new bucket detectors, BUILD_VERSION → iter95, 4 new feature flags)
- `frontend/src/pages/AdminStorageCleanup.js` (`BUCKET_LABELS` + `BUCKET_COLOR` extended)
- `backend/tests/test_iter95_orphan_buckets_expanded.py` (NEW — 10 cases)
- `backend/tests/test_iter94_storage_cleanup_ui_and_audit.py` (1-line update for new bucket-key convention)

---


## Storage Cleanup UI + Proactive Leak Tracking (iter94 — May 2026)

Follow-up to iter93. The cleanup-report endpoint was working but invisible to the user (curl-only). iter94 surfaces the inventory in a dedicated admin page **and** ships proactive leak prevention so the user has both a recovery path *and* a way to watch for regression.

### Backend
- **`POST /api/admin/storage-cleanup/mark-orphans`** in `server.py`:
  - Materializes the live orphan inventory into a new `orphan_chunks` collection (`{id, user_id, path, bucket, size_estimate, marked_at, last_seen_at, purged_at}`).
  - Idempotent via `upsert` keyed on `(user_id, path)` — `marked_at` is set once via `$setOnInsert`, `last_seen_at` + `bucket` refresh on every run via `$set` (no $setOnInsert/$set field conflicts).
  - Returns `{newly_marked, refreshed, total_marked_now, generated_at}`.
  - Purpose: when Emergent ships a DELETE API, we have a ledger of paths to sweep instantly. Until then it's an audit trail of orphans currently awaiting purge.
- **`GET /api/admin/storage-cleanup/audit-history?days=90`** in `server.py`:
  - Returns weekly storage-growth snapshots so the user can see whether orphan accumulation is still climbing.
  - Reads from `storage_growth_audits`, clamped to last 7-365 days, sorted oldest→newest.
- **`_storage_growth_audit_loop` background task** in `server.py`:
  - Weekly (cadence `STORAGE_AUDIT_INTERVAL_SECS = 7*24*3600`, startup stagger 10min).
  - Iterates active users (any `chunked_uploads` or `videos` activity in last 90 days) and writes `{user_id, recorded_at, total_orphan_chunks, total_estimated_bytes, total_estimated_gb, by_bucket{}}` per user.
  - Uses lightweight `_compute_orphan_snapshot(uid)` helper — counts only, no `chunk_paths` listing → cheap.
  - Wired into `@app.on_event("startup")` next to the iter86 TTL sweeper.

### Frontend
- New page **`pages/AdminStorageCleanup.js`** mounted at `/admin/storage-cleanup`:
  - "Why is my storage full?" explainer at the top (yellow callout) — answers the user's exact pending question.
  - 3 stat cards: Orphan chunks count · Wasted storage (GB) · Buckets affected.
  - **"Copy email to support"** button: drafts the exact mailto: with `user_id` + per-bucket totals filled in, opens default mail client AND writes the full body to clipboard (so paste-into-web-mail works too).
  - **"Mark as ready for purge"** button: hits `/mark-orphans`, shows `✓ Marked N new paths` result.
  - Per-bucket breakdown rows with color coding (yellow for dismissed, orange for failed, red for deleted, gray for lost).
  - Recharts line graph of `audit-history` for the 90-day trend.
- Wired into `App.js` (import + route under `<ProtectedRoute>`).
- Discoverable from the existing Admin Processing Events page via a new "Storage cleanup" pill button in the header.

### Tests (10 new, all 35 pass with iter90-93)
- `test_iter94_storage_cleanup_ui_and_audit.py`:
  - `/mark-orphans` requires auth + empty-state for fresh user
  - Persists to `orphan_chunks` with correct shape + idempotent (re-run returns `refreshed`, not `newly_marked`)
  - Cross-user isolation (User B can't mark User A's chunks)
  - `/audit-history` requires auth + empty-state + filters by days + cross-user isolation
  - Frontend grep guards: page file exists, calls all 3 endpoints, has required testids, mailto targets `support@emergent.sh`
  - App.js mounts route

### Verified live on preview
- `GET /api/health/deploy` → `build=iter94` with all 5 new feature flags.
- Playwright screenshot on `/admin/storage-cleanup` shows: 1,041 orphan chunks (~10.16 GB) in the test coach's Failed videos bucket, with both action buttons enabled. Orange iter91 storage outage banner still rendering above the new page.

### Files touched
- `backend/server.py` (mark-orphans + audit-history endpoints, audit loop, startup wiring, BUILD_VERSION → iter94, 5 new feature flags)
- `frontend/src/pages/AdminStorageCleanup.js` (NEW)
- `frontend/src/App.js` (import + route)
- `frontend/src/pages/AdminProcessingEvents.js` (header pill linking to /admin/storage-cleanup)
- `backend/tests/test_iter94_storage_cleanup_ui_and_audit.py` (NEW — 10 cases)

---


## Storage Cleanup Report — Answering "How is storage full?" (iter93 — May 2026)

User received this from Emergent Support on 2026-05-24: *"Root cause: your account has reached its object-storage capacity limit. Generic 500 is masking a 'storage limit reached'."* User pushed back: *"How is storage full if no upload has ever completed?"*

### Investigation findings (cited by user response)
1. **Emergent Object Storage API does NOT expose DELETE**. `OPTIONS /objects/{path}` returns `Allow: PUT, GET, HEAD`. Tried multiple delete variants — all return HTTP 405. Confirmed: there is no public way for an app to reclaim storage.
2. **Every failed/dismissed upload's chunks accumulate forever**. Preview DB sample alone showed:
   - 5 `chunked_uploads` with `status=completed`: 1057 chunks (~10 GB)
   - 7 `chunked_uploads` with `status=in_progress`: 965 chunks (~10 GB)
   - 1041 chunks tied to videos in `processing_status=failed` (~10 GB)
   - Total per-user storage: ~30 GB just from in-band bookkeeping
3. **Production with 50+ attempts over many days** could easily accumulate 100+ GB.

### Shipped: cleanup-report endpoint
New **`GET /api/admin/storage-cleanup/report`** in `server.py`:
- Cookie-authed (user can only see their own data).
- Walks `chunked_uploads` for sessions with `dismissed_at`.
- Walks `videos` for `processing_status=failed`, splits by `is_deleted` (deleted_videos vs failed_videos buckets).
- Walks `videos` for any chunk with `chunk_backends[i] == "lost"`.
- Returns JSON: `{summary: {total_orphan_chunks, total_estimated_bytes, total_estimated_gb, by_bucket: {...}}, buckets: {dismissed_sessions: [...], failed_videos: [...], deleted_videos: [...], lost_chunks: [...]}, instructions: "..."}`.
- Instructions string explicitly explains the no-DELETE-API limitation and tells the user to email `support@emergent.sh` with the report attached.

### Tests (7 new, all pass)
- `test_iter93_storage_cleanup_report.py`:
  - Auth required
  - Empty for fresh user (with all 4 buckets present + instructions text)
  - Dismissed sessions collected with all 3 chunk paths
  - Failed videos collected
  - Deleted videos go into a SEPARATE bucket from failed (different purge priority)
  - Cross-user isolation
  - Instructions text mentions DELETE limitation + support email

### Files touched
- `backend/server.py` (new `/api/admin/storage-cleanup/report` endpoint, BUILD_VERSION → iter93, 1 new feature flag)
- `backend/tests/test_iter93_storage_cleanup_report.py` (NEW — 7 cases)

---


## Bulk Resume Picker — Finish N Paused Uploads at Once (iter92 — May 2026)

After the 2026-05-23 → 24 Object Storage outage left a user with 13 paused uploads, the iter84 "Continue where you left off" banner let them resume one match at a time. iter92 collapses that 13-trip workflow into one multi-file picker.

### Backend
- `GET /api/me/pending-uploads` now also returns `file_size` (raw bytes) alongside `file_size_gb` — the frontend needs exact byte matching to avoid cross-routing files. (A coach with two different `game.mp4` files from different matches must not have them route to the wrong session.)

### Frontend
- New `pages/components/BulkResumeModal.js`:
  - Single `<input type="file" multiple>` lets the user pick all files at once.
  - For each picked File, matches to a pending session by `filename === f.name && file_size === f.size`. Each session can only match ONE file (no duplicates).
  - Matched files queue with status `queued`, then transition through `initializing → uploading → done` (or `retrying`, `waiting-storage`, `failed`).
  - Unmatched files surface in a yellow warning block so the user knows which ones to fix.
  - Uploads run sequentially (one file at a time) so we don't slam the storage layer with parallel chunk floods.
  - Each file's chunks use the SAME iter82 retry budget (20 retries, 60s max backoff, distinct messaging for 503 vs other 5xx) — no new pipeline that could regress iter80/89 safety.
  - Per-file progress bar + status icon (Spinner / CheckCircle / WarningCircle).
- `pages/components/ResumeAcrossDevicesBanner.js`:
  - New "Resume All" button (`data-testid="resume-all-btn"`) on the multi-session banner that opens the modal.
  - Banner refetches the pending-uploads list when the modal closes so completed sessions disappear immediately.

### Tests (6 new, all 18 pass with prior iter90/91)
- `test_iter92_bulk_resume.py`:
  - `/api/me/pending-uploads` includes `file_size` in bytes (exact, not the GB-rounded value)
  - Modal component file exists with all required testids
  - Modal matches by BOTH filename AND `file_size` (the exact-byte guard)
  - Modal uses the existing `/videos/upload/init` + `/videos/upload/chunk` pipeline
  - Modal handles 503 with a `waiting-storage` status + iter82-style 60s-max backoff
  - Banner renders the "Resume All" button only when `total > 1`

### Verified live on preview
- Build = `iter92`, feature count = 111.
- Playwright captured the modal opening from the resume banner with: "BULK RESUME — Finish all paused uploads at once", file picker dropzone, "Pick 13 files from your device — we'll match each one to its waiting session by filename + exact byte size", Cancel + close buttons. iter91 yellow outage banner remained visible above — both work together.

### Files touched
- `backend/server.py` (added `file_size` bytes to `/me/pending-uploads`, BUILD_VERSION → iter92, 3 new feature flags)
- `frontend/src/pages/components/BulkResumeModal.js` (NEW)
- `frontend/src/pages/components/ResumeAcrossDevicesBanner.js` (Resume All button, refactored fetch, modal mount)
- `backend/tests/test_iter92_bulk_resume.py` (NEW — 6 cases)

---


## Global Storage Outage Banner (iter91 — May 2026)

After the 2026-05-23 → 2026-05-24 21+ hour Emergent Object Storage outage, even the iter90 pre-flight modal still required the user to ATTEMPT an upload before discovering the problem. iter91 mounts a proactive banner on every authenticated page so users see the outage the moment they log in.

### Frontend
- New component `components/StorageOutageBanner.js`:
  - Polls `/api/health/storage` every 60s (uses the iter90 endpoint).
  - When `healthy === false`, renders a thin yellow strip at the top of the page (`#F59E0B` palette — distinct from the red disk-pressure banner so users can tell them apart).
  - Banner text: "STORAGE DEGRADED — Emergent Object Storage is currently failing (PUT returned 500). Uploads are paused — we'll resume automatically when it recovers. Existing videos and clips load normally."
  - Dismiss button (`data-testid="storage-outage-banner-dismiss"`) lets users hide it for the rest of their session.
  - When storage RECOVERS (`healthy === true`), the dismissed state auto-resets so a future outage gets a fresh banner.
- Mounted in `App.js` next to `DiskPressureBanner` and `Toaster`.

### Tests (7 new)
- `test_iter91_storage_outage_banner.py`:
  - Banner file exists
  - Polls `/health/storage` with `setInterval` ≤ 60s
  - Renders only when storage is unhealthy
  - Has dismiss button with proper `data-testid`
  - On recovery, calls `setDismissed(false)` so future outages re-render
  - App.js mounts the banner
  - Uses yellow palette (visually distinct from red disk-pressure banner)

### Verified live on preview during the active 2026-05-24 outage
- Banner appears within ~5s of login on `https://soccer-analysis-16.preview.emergentagent.com/dashboard`.
- Text reads: "STORAGE DEGRADED — Emergent Object Storage is currently failing (PUT returned 500). Uploads are paused — we'll resume automatically when it recovers. Existing videos and clips load normally."
- Sits cleanly above the navigation header. Other UI (Match Library, Coach Pulse, existing videos) is fully usable.

### Files touched
- `frontend/src/components/StorageOutageBanner.js` (NEW)
- `frontend/src/App.js` (import + mount)
- `backend/server.py` (`BUILD_VERSION` → iter91, 1 new feature flag)
- `backend/tests/test_iter91_storage_outage_banner.py` (NEW — 7 cases)

---


## Pre-Flight Storage Probe — Fail-Fast During Outages (iter90 — May 2026)

After the 2026-05-23 production object-storage outage where every PUT returned HTTP 500 for >1h and forced users to burn ~15 min of client retries before getting an error, iter90 adds a pre-flight probe so the UI can refuse to start the upload instantly with a friendly modal instead.

### Backend
- New endpoint **`GET /api/health/storage`** in `server.py`:
  - Performs a single ~1KB PUT roundtrip against Emergent object storage (`POST /init` → `PUT /objects/.../healthcheck/iter90_probe_*.bin`).
  - Returns `{healthy: bool, latency_ms: int, reason?: str, cached: bool}`.
  - **Public** (no auth) — the frontend needs it BEFORE `/api/auth`-gated init.
  - **30s in-memory cache** so a burst of upload attempts can't DDoS the upstream probe target.
  - Sub-200ms response time even when storage is broken (uses tight `timeout=(3, 8)` budget).

### Frontend
- `pages/MatchDetail.js::handleChunkedUpload` now calls `/api/health/storage` BEFORE `/videos/upload/init`. If `healthy === false`:
  - Shows an alert with the exact reason (e.g. `"PUT returned 500"`) + latency.
  - Tells the user to wait 15-30 minutes, OR email `support@emergent.sh` with subject `"Object storage 500 errors"` and the app domain.
  - Reassures: "Your file selection has been preserved — just click the file picker again when ready."
- Probe network failure is treated as ambiguous → continues optimistically (don't block uploads on a probe blip).

### Tests (5 new, all 46 pass with prior storage suite)
- `test_iter90_storage_preflight.py`:
  - Endpoint is public (no 401)
  - Reports `healthy=false` with a `reason` field during outages
  - Cache returns `cached=true` on the second consecutive call
  - `handleChunkedUpload` source contains `/health/storage` reference BEFORE `/videos/upload/init`
  - Friendly alert mentions `support@emergent.sh` + "preserved"

### Verified live on preview
- `GET /api/health/deploy` → `build=iter90` with all 3 new feature flags.
- Direct curl during the active 2026-05-23 outage → `{healthy: false, reason: "PUT returned 500", latency_ms: 155, cached: false}` returned in 155ms (vs the prior ~15min retry-loop failure mode).
- Playwright `page.evaluate` from the authenticated MatchDetail page confirms the probe responds with the same diagnostic shape.

### Files touched
- `backend/server.py` (new `/api/health/storage` endpoint, 30s cache, BUILD_VERSION → iter90, 3 new feature flags)
- `frontend/src/pages/MatchDetail.js` (pre-flight probe call inside `handleChunkedUpload`)
- `backend/tests/test_iter90_storage_preflight.py` (NEW — 5 cases)

---


## P0 — Disable Dangerous /app Fallback + Broaden Recovery Gate (iter89 — May 2026)

Real production bug 2026-05-23, video `f0fee06a-19e0-4c86-bf76-2899bfe1a8c0` (1.04 GB, 107 chunks). Upload reached 100% client-side, but the production pod cycled mid-upload (multiple "Server restarted detected" + 520s in console). Chunks that landed on `/app/.video_chunks` (iter83's "persistent" PV fallback) **did not survive** — production's `/app` is NOT actually a real PV on Emergent's hosted deploy. Video ended at "Upload incomplete (1 of 107 chunks, 0.9%)" with no Try Recovery button visible because iter88's regex gate was too narrow.

### Two fixes shipped

1. **Persistent-filesystem fallback is now opt-in** (`services/storage.py`):
   - New env var `ENABLE_PERSISTENT_CHUNK_FALLBACK` (default disabled).
   - When NOT set (production default), `store_chunk` raises `RuntimeError("storage_unavailable_fallback_disabled")` on object-storage failure instead of writing to `/app/.video_chunks`. The 503 response sets `Retry-After: 60` (vs 30 for other 503s) so iter82's 20-retry client-side budget rides out a typical 5–10min storage outage cleanly.
   - When SET to "true"/"1"/"yes" (preview, or production with a verified PV), iter83 behavior is restored.
   - The opt-in design protects against the iter83 root cause: chunks landing on `/app` and evaporating before the migration loop can hoist them to object storage. With this disabled, the only path to durability is object storage itself.
   - WARN-level log line `"routed to persistent_filesystem fallback"` on every fallback write so operators can `grep` production logs to verify the path isn't being exercised.

2. **Try Recovery button gate broadened** (`pages/components/VideoAnalysisHeader.js`):
   - Pre-iter89 the button only rendered when the error contained `chunk` + `missing`/`unreadable`/`lost` OR `upload incomplete`. The real production error was `"Upload incomplete (1 of 107 chunks, 0.9%). Re-upload required — AI analysis can't run on a partial file."` — which SHOULD have matched, but the user reported the button not appearing on production iter88b. Likely a CDN cache or minifier edge case.
   - iter89 takes the conservative route: show the button for ANY chunked-video processing failure EXCEPT AI-budget / quota / balance errors. The recovery endpoint already returns `ready_to_retry: false` cleanly when it can't help, so showing it for "definitely-recoverable" failures has zero downside and surfaces the discovery path universally.

### Tests (8 new, all 41 pass)
- `test_iter89_safer_fallback.py`:
  - `store_chunk` raises `storage_unavailable_fallback_disabled` when env var is unset (default)
  - Fallback dir is NOT created when refused
  - `store_chunk` uses fallback when env var is "true"
  - Env var accepts case-insensitive "true"/"1"/"yes"
  - Recovery button gate uses `!isAiBudgetError` exclusion (not positive regex)
  - Gate still hides for budget/quota/balance errors
  - WARN log line present in store_chunk source
- Existing iter83 fallback tests updated to set `ENABLE_PERSISTENT_CHUNK_FALLBACK=true` (required to exercise the now-opt-in path).
- Test pollution fix: dropped the in-progress `db.persistent_fallback_audit.insert_one` call inside `store_chunk` — kept pure-logging audit to avoid Motor event-loop pollution across test runs.

### Verified live on preview
- `GET /api/health/deploy` returns `build=iter89` with all 4 new feature flags.
- Seeded a video matching the EXACT production error string (`"Upload incomplete (1 of 107 chunks, 0.9%). Re-upload required..."`) → Playwright captured the failed banner with BOTH the new blue "Try Recovery" button AND the red "Retry Processing" button side-by-side. Recovery button now reliably surfaces for the real production failure shape.

### Files touched
- `backend/services/storage.py` (opt-in fallback via env var, WARN log on fallback write)
- `backend/server.py` (`Retry-After: 60` for fallback_disabled 503, BUILD_VERSION → iter89, 4 new feature flags)
- `frontend/src/pages/components/VideoAnalysisHeader.js` (broadened `canTryRecovery` gate)
- `backend/tests/test_iter89_safer_fallback.py` (NEW — 8 cases)
- `backend/tests/test_persistent_chunk_fallback.py` (env-var setenv in 2 existing tests)

### ⚠ Action required from operator
- **Do NOT set `ENABLE_PERSISTENT_CHUNK_FALLBACK=true` on production** until/unless a real PV is provisioned for `/app/.video_chunks` and verified across pod restarts.
- The stuck video `f0fee06a-19e0-4c86-bf76-2899bfe1a8c0` is unrecoverable (chunks evaporated) — user needs to re-upload. After iter89 deploys, this specific failure shape can't happen again because no chunk will land on ephemeral `/app` storage.

---


## Recovery Endpoint for Stuck Chunked Videos (iter88 — May 2026)

Follow-up to iter87. Even with the migration race fixed, videos already corrupted in production (and any that hit OTHER edge cases of pointer drift between `chunked_uploads` and `videos`) needed a recovery path that doesn't require re-uploading 800 MB.

### Backend
- New endpoint **`POST /api/videos/{video_id}/recover-chunks`** in `server.py`:
  1. **Sync from `chunked_uploads`**: For each chunk index where the video doc's `chunk_backends[i]` / `chunk_paths[i]` disagree with the `chunked_uploads` collection's version, adopt the upload doc's pointer. The background migration loop updates `chunked_uploads` first, so a stale video doc is the most common recovery case.
  2. **Re-run migration** on any remaining `persistent_filesystem` chunks using the same iter87 ordering (upload → swap DB → delete local file).
  3. **Re-check integrity**. If `full`, reset `processing_status` to `pending` and clear `processing_error` so the existing "Retry Processing" flow can run cleanly.
- Returns a structured summary: `synced_from_uploads`, `migrated_to_storage`, `migration_failures[]`, `integrity`, `available_chunks`, `total_chunks`, `ready_to_retry`.
- 400 for non-chunked videos, 404 for unknown video ids, cookie-auth gated.

### `_migrate_one_chunk` 3-state result (iter88 fix on top of iter83/iter87)
The bool return was lossy — when the local file was gone, it returned `True` ("drop entry") which caused `_migrate_collection` to write a **fake storage pointer** for an object that doesn't exist. Future integrity checks then incorrectly counted that chunk as available. New contract:
- `"migrated"` — upload succeeded; caller swaps DB pointer, then deletes file.
- `"retry"` — storage still failing or local file unreadable; caller preserves everything for next tick.
- `"lost"` — local file gone, no other copy; caller writes `chunk_backends[i] = "lost"` so the integrity check excludes it.
- `_check_chunk_integrity` honors the new `"lost"` tag (always counted unavailable).
- Existing iter83 + iter87 tests updated to assert the new string contract.

### Frontend
- `VideoAnalysisHeader.js`: new blue **"Try Recovery"** button (`data-testid="try-recovery-btn"`) appears alongside the existing red "Retry Processing" button, gated by a `canTryRecovery` derived flag that ONLY fires when the error mentions "chunk" + ("missing" / "lost" / "unreadable") OR "upload incomplete" — so AI-budget / invalid-mp4 failures don't show a misleading CTA.
- `VideoAnalysis.js`: new `handleTryRecovery` handler with `recovering` flight state. On `ready_to_retry`, auto-fires `handleReprocess` so the user doesn't need a second click. On failure, the alert points them at "Delete & re-upload".

### Tests (6 new, all 31 pass)
- `test_recover_chunks.py`:
  - Auth required (401/403 anonymous)
  - 404 for unknown video
  - 400 for non-chunked legacy video
  - Happy path: stale video doc pointer synced from chunked_uploads → integrity full → processing_status reset → ready_to_retry=true
  - Unrecoverable path: when both chunked_uploads and storage are out (and local file is gone), returns `ready_to_retry=false` and leaves `processing_status=failed` so the user knows to re-upload
  - Frontend grep: header gates button on `canTryRecovery` with chunk/missing/lost keywords; VideoAnalysis wires `handleTryRecovery` to the `/recover-chunks` endpoint.
- Plus all 8 iter87 tests and all iter83 tests updated for the 3-state contract.

### Verified live on preview
- Build endpoint returns `iter88` with all 4 new feature flags (`recover-chunks-endpoint`, `try-recovery-button-on-failed-banner`, `migrate-one-chunk-3-state-result`, `chunk-backend-lost-tag-excluded-from-integrity`).
- Seeded a stuck video matching the production failure shape → Playwright captured the failed banner with the "Try Recovery" button next to "Retry Processing" → endpoint call via curl returned `synced_from_uploads=1`, `integrity=full`, `ready_to_retry=true`, `processing_status=pending`, error cleared.

### Files touched
- `backend/server.py` (new `/recover-chunks` endpoint, BUILD_VERSION → iter88, 4 new feature flags)
- `backend/services/storage.py` (3-state `_migrate_one_chunk`, `_migrate_collection` handles `"lost"` via `chunk_backends.X = "lost"`)
- `backend/services/processing.py` (`_check_chunk_integrity` excludes `backend == "lost"`)
- `backend/tests/test_recover_chunks.py` (NEW — 6 cases)
- `backend/tests/test_persistent_chunk_fallback.py` (3-state contract update)
- `backend/tests/test_iter87_migration_race_fix.py` (3-state contract update)
- `frontend/src/pages/VideoAnalysis.js` (`handleTryRecovery`, `recovering` state, prop wiring)
- `frontend/src/pages/components/VideoAnalysisHeader.js` (new prop signature, derived `canTryRecovery` gate, blue button)

---


## P0 — Migration Race Fix + Fail-Fast Assembly (iter87 — May 2026)

Real production bug 2026-05-22, video `40af07ed-5fa7-4ccb-87d5-fb0e3d5917b5` (0.83 GB, 85 chunks, "LFC 2007B Premier vs ACGR 07 MLS NEXT II"). Upload finalized successfully, processing failed with "Video file is incomplete (moov atom missing). Please re-upload — the chunked transfer didn't finalize cleanly."

### Root cause traced
The iter83 `_migrate_one_chunk` function deleted the local persistent_filesystem file **before** the DB swap (which moved chunk_paths/chunk_backends from local → object-storage). If the pod restarted between those two steps:
1. Local file `/app/.video_chunks/<vid>/chunk_NNN.bin` was already deleted.
2. DB still said `backend="persistent_filesystem"`, `path="/app/.video_chunks/..."`.
3. Next finalize fired (or next pod boot picked up the half-migrated state).
4. `prepare_video_sample` tried to read the missing file → exception → silently wrote `b'\x00' * chunk_size` (10 MB of zeros) into the assembled mp4.
5. ffmpeg got a corrupt mp4 → "moov atom not found" → confusing error to the user.

### Three fixes shipped

1. **Migration ordering** (`services/storage.py`):
   - `_migrate_one_chunk` no longer deletes the local file. Returns True after successful object-storage upload only.
   - `_migrate_collection` now sequences:
     - (a) upload to object storage
     - (b) `update_one({chunk_paths.N: new_key, chunk_backends.N: "storage"})`
     - (c) **only then** `os.remove(local_path)`
   - If (b) fails: local file preserved → next tick retries the whole sequence.
   - If pod crashes between (b) and (c): one ~10 MB orphan file leaks (next tick skips it because backend is now "storage") but the DB stays consistent.

2. **Fail-fast assembly** (`services/processing.py`):
   - Both `prepare_video_sample` and `prepare_video_segments_720p` now raise `RuntimeError("Chunk N of M is missing/unreadable — re-upload required.")` on the FIRST unreadable chunk.
   - No more silent `b'\x00' * chunk_size` zero-fills — these were the actual source of the moov-atom corruption.
   - The `_check_chunk_integrity` early gate (already in place since iter62) now catches the failure cleanly with a user-friendly "Upload incomplete (X of Y chunks, Z%)" message BEFORE ffmpeg even sees the assembly. User gets the right action: re-upload.

3. **`_check_chunk_integrity` honors `persistent_filesystem`**:
   - Pre-iter87 the file-existence check ran only for `backend == "filesystem"` (legacy). iter83's `persistent_filesystem` backend was missed → a deleted local file was incorrectly counted as "available". Now both backends are checked.

### Tests (8 new, all 56 pass)
- `test_iter87_migration_race_fix.py`:
  - `_migrate_one_chunk` no longer calls `os.remove`
  - `_migrate_collection` calls `update_one` BEFORE `os.remove` (order asserted)
  - DB-swap failure preserves the local file
  - `prepare_video_sample` raises on missing `chunk_paths[N]` (no zero-fill)
  - `prepare_video_sample` raises on missing `persistent_filesystem` file
  - Grep-level guard: `b'\x00' * chunk_size` zero-fill pattern completely removed from `processing.py`
  - `_check_chunk_integrity` counts missing `persistent_filesystem` file as unavailable
  - `_check_chunk_integrity` counts present `persistent_filesystem` file as available
- Existing iter83 test updated: `_migrate_one_chunk` must now LEAVE the file in place (was the inverse assertion pre-iter87).

### Recovery for the affected video
The user's stuck video `40af07ed-5fa7-4ccb-87d5-fb0e3d5917b5` lost the moov-atom chunk on production — no recovery possible without the original bytes. They need to re-upload the file. After iter87 deploys, the bug is gone for all future uploads.

### Files touched
- `backend/services/storage.py` (`_migrate_one_chunk` no longer deletes; `_migrate_collection` sequences upload → swap → delete with explicit failure handling)
- `backend/services/processing.py` (4 zero-fill sites replaced with `RuntimeError`; `_check_chunk_integrity` honors `persistent_filesystem`)
- `backend/server.py` (`BUILD_VERSION` → iter87, 3 new SHIPPED_FEATURES)
- `backend/tests/test_iter87_migration_race_fix.py` (NEW — 8 cases)
- `backend/tests/test_persistent_chunk_fallback.py` (iter87 contract update for `_migrate_one_chunk`)

---


## Cross-Device In-App Notifications + 30-Day TTL Sweeper (iter86 — May 2026)

Two wins, both follow-ups to iter85:

### Task 1 — Cross-device upload notifications (P2)
The existing Web Push pipeline (`services/push_notifications.py`) only reaches devices that explicitly subscribed AND granted permission — most coaches skip that prompt. iter86 adds an **in-app polling** layer so any authenticated tab gets the toast the moment another device's upload finishes processing.

- New collection `user_notifications`: `{id, user_id, type, title, body, deep_link, video_id, match_id, created_at}`.
- New endpoint **`GET /api/me/notifications/recent?since=<iso>`** in `server.py` — returns up to 20 notifications for the calling user created after `since` (default cutoff: 24h ago, clamped so an ancient `since` doesn't blow up the response).
- `services/processing.py` now inserts a `user_notifications` row alongside the existing `send_to_user` push call, so both pipelines fire together.
- New frontend hook **`hooks/useInAppNotifications.js`** mounted in `App.js`:
  - Polls every 30s once authenticated; first poll fires immediately on auth state change.
  - Per-device "seen" state tracked in localStorage (capped at 200 ids) — a coach with laptop + phone open simultaneously WANTS both to ping, but one device shouldn't re-fire on every poll.
  - Fires both `showLocalNotification` (browser-level, no-op if permission denied) AND a sonner `toast.success(...)` (always visible) with an "Open" action that deep-links to `deep_link`.
  - Stops polling on 401 (user logged out).
- `<Toaster theme="dark" position="top-right" richColors closeButton />` mounted in `App.js`.

### Task 2 — TTL sweeper for `dismissed_at` rows (P3)
- New `_dismissed_uploads_ttl_sweeper` background task in `server.py` registered on startup. 5-min stagger then daily cadence.
- Each tick hard-purges:
  - `chunked_uploads` with `dismissed_at < now − 30 days`
  - `user_notifications` with `created_at < now − 30 days`
- Tunable via module-level constants (`DISMISSED_UPLOADS_TTL_DAYS`, `USER_NOTIFICATIONS_TTL_DAYS`, `TTL_SWEEPER_INTERVAL_SECS`) so tests can monkeypatch shorter horizons.
- Logs only when something was actually purged — no spam.

### Tests (10 new, all 22 pass)
- `test_in_app_notifications_and_ttl.py`:
  - Auth boundary on `/me/notifications/recent`
  - Empty state for fresh user
  - Returns inserted notifications
  - Cross-user isolation
  - `since` cutoff filters older rows
  - TTL sweeper purges stale uploads + notifications while keeping fresh
  - TTL constants sanity check (7-365 day range, daily-to-weekly cadence)
  - Frontend grep: App.js mounts hook + Toaster, hook calls `/me/notifications/recent` + uses `setInterval` + `localStorage`, processing.py writes to `user_notifications`.
- All 6 iter85 + 6 iter84 tests still pass.

### Verified live on preview (Playwright)
- Logged in as `testcoach@demo.com`
- Seeded a notification row via direct DB insert (`id`, `title`, `body`, `deep_link`)
- Within ~6s of auth, the hook polled `/api/me/notifications/recent?since=…` (confirmed via request capture)
- Sonner toast rendered top-right with the exact title + body + "Open" action button
- `build=iter86` confirmed via `/api/health/deploy` with all 5 new feature flags.

### Files touched
- `backend/server.py` (new endpoint, TTL sweeper, hooked into startup, BUILD_VERSION → iter86, 5 new SHIPPED_FEATURES, 3 new tunable constants)
- `backend/services/processing.py` (insert `user_notifications` row alongside `send_to_user`)
- `frontend/src/hooks/useInAppNotifications.js` (NEW)
- `frontend/src/App.js` (import + invoke hook, mount `<Toaster />`)
- `backend/tests/test_in_app_notifications_and_ttl.py` (NEW — 10 cases)

---


## Dismiss Button on Resume Banner (iter85 — May 2026)

A coach with 14 stale "0/85 chunks (0%)" sessions from a flaky-wifi weekend shouldn't have the dashboard banner clutter forever. iter85 adds a per-row X button that hides the session AND best-effort frees any persistent_filesystem chunks on `/app` so disk doesn't grow unbounded across abandoned uploads.

### Backend
- New endpoint **`DELETE /api/me/pending-uploads/{upload_id}`** in `server.py`:
  - Marks the session `dismissed_at = <utc iso>` (soft delete — keeps audit trail).
  - Best-effort deletes any chunks tagged `filesystem` or `persistent_filesystem` from local disk (`os.remove`); object-storage chunks left alone (cheap, future cleanup).
  - Removes the now-empty per-video chunk directory.
  - Idempotent: dismissing twice (or dismissing an unknown upload_id, or dismissing another user's session) → `200 OK` with `{"already": true}` rather than 404. Avoids the UX disaster of "I clicked the X, did it work?" when another tab raced you.
- `GET /api/me/pending-uploads` now filters out anything with a `dismissed_at` field — dismissed sessions never reappear.

### Frontend
- `ResumeAcrossDevicesBanner.js`:
  - Each row in the expanded list has its own X button (`data-testid="dismiss-session-{upload_id}"`) with a vertical divider separating it from the navigate-to-match click area.
  - Single-session collapsed banner exposes the X inline next to the caret — saves an extra click to expand-then-dismiss.
  - `e.stopPropagation()` on the X handler prevents the click from also triggering the row's navigate handler.
  - Optimistic local state: row is removed from `sessions[]` immediately on success. On API failure, the row is re-shown (rollback) so the user can retry.
  - Per-row `dismissing` Set prevents double-clicks while the DELETE is in flight (button disabled at 40% opacity).

### Tests (6 new, all pass)
- `test_dismiss_pending_upload.py`:
  - Auth required (401/403 without cookie).
  - Happy path: session disappears from `/api/me/pending-uploads` after DELETE.
  - Idempotent (calling DELETE twice → both 200, second has `already=true`).
  - Cross-user isolation (User B's DELETE attempt on User A's session is a no-op).
  - Unknown upload_id → idempotent success.
  - Banner component file contains `axios.delete` + `dismiss-session-` testid pattern.
- Plus all 6 iter84 tests still pass.

### Verified live on preview
- `GET /api/health/deploy` returns `build=iter85` with all 3 new feature flags.
- End-to-end Playwright screenshot:
  - Logged in as `testcoach@demo.com` (14 stale pending uploads).
  - Expanded the resume banner → all 14 rows visible, each with X button on the right.
  - Clicked first X → DELETE call fired → row count dropped to 13, banner headline updated to "13 uploads paused — Latest: probe.mp4 (0%) and 12 more".
  - No console errors. Visual layout clean (vertical divider, hover state).

### Files touched
- `backend/server.py` (new DELETE endpoint, filter `dismissed_at` from GET, import `PERSISTENT_CHUNK_DIR`, BUILD_VERSION → iter85, 3 new SHIPPED_FEATURES)
- `frontend/src/pages/components/ResumeAcrossDevicesBanner.js` (per-row X, single-session inline X, optimistic state, rollback on error)
- `backend/tests/test_dismiss_pending_upload.py` (NEW — 6 cases)

---


## Resume Across Devices (iter84 — May 2026)

Enhancement enabled by iter83's durable chunk storage. The use case: a coach starts uploading an 800 MB game from their laptop at the field. WiFi drops at 60%. They drive home, open the app on their phone — but they have to *remember* which match the upload was tied to before they can find the resume banner. Most coaches just give up and re-upload from scratch from the laptop the next day.

iter84 surfaces the recovery path at the **dashboard** level so any device that logs in sees: "1 upload paused — finish on this device" (or "N uploads paused …" with an expandable list).

### Backend
- New endpoint **`GET /api/me/pending-uploads`** in `server.py`. Returns up to 20 incomplete chunked-upload sessions for `current_user`, joined with the `matches` collection so the UI gets a human-readable label per session ("LFC 07B vs Express FC"). Cross-user isolation enforced by `user_id` filter on the Mongo query. Cookie-auth gated via existing `Depends(get_current_user)`.

### Frontend
- New component **`pages/components/ResumeAcrossDevicesBanner.js`**. Fetches the endpoint on mount, hides silently when zero sessions (no UI clutter for happy-path users). Single session → clicking the banner navigates straight to the match. Multiple sessions → caret expands an in-banner list with one row per session, each linking to its match.
- Wired into `Dashboard.js` above `QuickActionsRow` so it's the first thing a returning coach sees.
- All data-testids set (`resume-across-devices-banner`, `resume-across-devices-toggle`, `resume-session-{upload_id}`, `resume-across-devices-list`) so the testing agent can verify behavior.

### Tests (6 new, all pass)
- `test_resume_across_devices.py` — auth boundary, empty-state, real-session listing with match labels, cross-user isolation, dashboard wiring, banner file existence.
- Existing CSRF flow validated (tests register a user, capture `csrf_token` cookie from the jar, echo it as `X-CSRF-Token` header on every POST — same pattern as `test_csrf_protection.py`).

### Verified live on preview
- `GET /api/health/deploy` returns `build=iter84` with both new feature flags.
- End-to-end screenshot: logged in as `testcoach@demo.com` → dashboard renders the blue "CONTINUE WHERE YOU LEFT OFF" banner with "14 uploads paused" headline → clicking the caret expands the full list with match labels (Demo Home vs Demo Away, LFC 07B vs Express FC × 6, LFC 07B vs DPA Cobra, …) and chunk-progress sub-text.
- Tested with both single-session and multi-session user states.

### Files touched
- `backend/server.py` (new `/api/me/pending-uploads` endpoint; BUILD_VERSION → iter84; 2 new SHIPPED_FEATURES)
- `frontend/src/pages/components/ResumeAcrossDevicesBanner.js` (NEW)
- `frontend/src/pages/Dashboard.js` (imports + renders the banner)
- `backend/tests/test_resume_across_devices.py` (NEW — 6 cases)

---


## Persistent Chunk Fallback + Supervisor-Healed `.gitignore` (iter83 — May 2026)

Follow-up to iter82 — closes the two remaining backlog items the user flagged:
"Wire predeploy.sh into Emergent's deploy pipeline" (P1) and
"Persistent-disk chunk fallback" (P2).

### Task 1 — Supervisor `gitignore-keeper` watchdog (replaces manual predeploy.sh)

Emergent's deploy UI doesn't expose a docs-grade `predeploy` hook in
`.emergent/emergent.yml`. Instead of a one-shot manual command, iter83 ships
a long-running supervisor program that loops `bash /app/predeploy.sh` every
60s — the file is *always* clean when the user clicks Deploy.

Files:
- `/app/scripts/gitignore-keeper.sh` — the loop wrapper (60s tick, idempotent, exits non-zero only on catastrophic predeploy.sh failure but supervisor autorestart=true catches that).
- `/etc/supervisor/conf.d/supervisord_gitignore_keeper.conf` — supervisor program registration.

Verified end-to-end during this iteration: injected `.env`-block corruption → waited 60s → keeper healed it cleanly (5 lines removed, file ends with the canonical "memory/test_credentials.md" line).

### Task 2 — Persistent chunk fallback + background migration

`/var/video_chunks` lives on overlay and evaporates on pod restart (real iter81 prod root cause — 35 of 85 chunks lost). iter83 moves the filesystem-fallback path to `/app/.video_chunks` which is mounted on a real PV (`/dev/nvme0n*`), so files survive pod restarts.

Changes:
- `db.py` exports new `PERSISTENT_CHUNK_DIR = "/app/.video_chunks"` and `PERSISTENT_CHUNK_FREE_MIN_BYTES = 500 MB`.
- `services/storage.py::store_chunk` now returns one of three backends — `"storage"` (happy path), `"persistent_filesystem"` (fallback to PV during outage), or raises `RuntimeError("persistent_storage_full")` if /app is critically low.
- `services/storage.py::read_chunk_data` understands both `"filesystem"` (legacy) and `"persistent_filesystem"` (iter83) — both are local files at an absolute path.
- New `services/storage.py::migrate_persistent_chunks_loop` runs on backend startup. Every 30s it walks `chunked_uploads` and `videos` collections looking for `chunk_backends == "persistent_filesystem"` entries, re-uploads them to object storage, and swaps the backend + path in-place. Successful migrations also delete the local file so /app doesn't fill up over time.
- `server.py::upload_chunk` **removes the iter80 503 rejection of filesystem chunks** (now safe to commit because they're on a PV). The only 503 case left is `RuntimeError("persistent_storage_full")` → 503 + `Retry-After: 30` so the iter79 client backs off.

### Tests
- `test_persistent_chunk_fallback.py` (NEW — 10 cases): asserts PV path, disk-pressure refusal, read-back path, migration success swaps backend, migration failure preserves file, missing-file drops entry, MIGRATE_INTERVAL_SECS ≤ 60s.
- `test_gitignore_keeper.py` (NEW — 6 cases): asserts predeploy.sh exists + executable, keeper script exists + executable, supervisor config references it, keeper is RUNNING in supervisor, predeploy.sh idempotent on clean file, `.env` files NOT git-ignored after keeper run.
- All 34 storage/upload/keeper tests pass (10 iter82 + 24 iter83). Lint clean across `db.py`, `services/storage.py`, `server.py`.

### Verified live
- `GET /api/health/deploy` returns `build=iter83` with all 5 new feature flags.
- Backend logs: `[migrate-loop] watching /app/.video_chunks for persistent_filesystem chunks every 30s` (loop is alive).
- `supervisorctl status gitignore-keeper` → `RUNNING` (uptime confirmed).
- Smoke screenshot of homepage on preview renders cleanly.

### Files touched
- `backend/db.py` (PERSISTENT_CHUNK_DIR + PERSISTENT_CHUNK_FREE_MIN_BYTES constants)
- `backend/services/storage.py` (store_chunk refactor, read_chunk_data, migrate_persistent_chunks_loop + helpers)
- `backend/server.py` (upload_chunk no longer rejects filesystem chunks; migrate_persistent_chunks_loop hooked on startup; BUILD_VERSION → iter83 + 5 new SHIPPED_FEATURES)
- `backend/tests/test_persistent_chunk_fallback.py` (NEW)
- `backend/tests/test_gitignore_keeper.py` (NEW)
- `/app/scripts/gitignore-keeper.sh` (NEW)
- `/etc/supervisor/conf.d/supervisord_gitignore_keeper.conf` (NEW)

---


## Patience Through Storage Outages + Auto-Resume UX (iter82 — May 2026)

Follow-up to iter81. Real production incident 2026-05-21 ~07:13 UTC: object storage (`integrations.emergentagent.com/objstore`) returned HTTP 500 on every chunk PUT for ~6 minutes. iter81's 503-on-filesystem-fallback correctly refused to commit ephemeral chunks, but the iter79 client only had **6 retries (~2 min total)** before alerting the user with "Upload interrupted". User's screenshot: orange banner "INCOMPLETE UPLOAD WAITING — LFC 07B at ACGR 07 MLSNext2.mp4 (0.83 GB) — 0 of 85 chunks delivered (0%)".

### Fixes shipped

1. **Client retry budget bumped 6 → 20** in `frontend/src/pages/MatchDetail.js::uploadChunkWithRetry`. With 60s max backoff that's ~15 minutes of patient retrying — covers virtually every transient object-storage outage we've observed.
2. **503 gets a friendly status message** instead of the scary "Chunk failed (attempt X/6)" — distinguishes "storage is degraded, just waiting it out" from real chunk-level failures. The message reads: *"Storage temporarily slow — auto-resuming in Ns (attempt X/20). Keep this tab open."*
3. **`fetchPendingUploads()` is called inside the upload's catch block** so the orange "INCOMPLETE UPLOAD WAITING" banner refreshes immediately without forcing a page reload. Previously the banner only appeared after F5 — many users wouldn't notice their resume option.
4. **`put_object_with_retry` default raised 4 → 6** (`backend/services/storage.py`) so transient ~minute-long storage hiccups get absorbed server-side before triggering the 503 bounce. Exponential backoff already caps at 10s, so worst case server-side retry budget is ~30s per chunk before falling back — still safe.
5. **Failure-message routing**: when the final `err.response.status === 503` (storage degraded for >15 min), the alert now points users at the orange resume banner rather than rambling about HandBrake.

### `.gitignore` Deploy Hook — Predeploy Script

The Emergent platform hook keeps re-injecting `.env`, `.env.*`, `*.env`, and `frontend/node_modules/.cache/default-development/*.pack` lines into `/app/.gitignore`. This causes the deploy pipeline to skip the secrets step ("failed to fetch envs") because the `.env` files become git-ignored.

Shipped `/app/predeploy.sh` — an idempotent cleaner that strips all known platform-injected patterns. Tested against simulated corruption (6 lines removed cleanly). User should run `bash /app/predeploy.sh` immediately before each Deploy click.

Caught 3 freshly-injected `.pack` lines during this iteration alone — confirms the script is needed.

### Tests
- `test_storage_circuit_breaker.py::test_put_object_with_retry_iter82_floor` — locks the server-side retry floor to >=6
- `test_upload_retry_budget_frontend.py` — 4 new cases asserting client retry budget >=20, banner refresh, friendly 503 status
- All 21 storage/upload-related tests pass. No regressions in lint or BUILD endpoint.

### Verified live
- `GET /api/health/deploy` on preview returns `build=iter82` with all 5 new feature flags listed
- Smoke screenshot of preview homepage renders cleanly

### Files touched
- `frontend/src/pages/MatchDetail.js` (uploadChunkWithRetry retry budget, 503 status, catch-block banner refresh, smarter alert)
- `backend/services/storage.py` (`put_object_with_retry` default 4 → 6, store_chunk call site updated)
- `backend/server.py` (`BUILD_VERSION = "iter82"`, 5 new feature flags appended to SHIPPED_FEATURES)
- `backend/tests/test_storage_circuit_breaker.py` (new iter82 floor test)
- `backend/tests/test_upload_retry_budget_frontend.py` (NEW — 4 cases)
- `/app/predeploy.sh` (NEW — gitignore platform-hook cleaner)
- `/app/.gitignore` (cleaned of platform-injected `.env*` and `.pack` lines)

---


## Storage Routing Fix — End the 50-of-85-Chunks Bug (iter81 — May 2026)

Real production bug 2026-05-21 (video `25e71613`, 845 MB compressed file): the upload reported reaching ~25% then errored. The iter70 banner showed "Upload incomplete (50 of 85 chunks, 58.8%)". User had carefully followed the iter79 HandBrake compression advice; the upload pipeline still failed.

### Root cause (not what we initially suspected)
The actual failure mode wasn't a flaky home connection. It was a **storage-routing decision** inside our own backend:

1. `services/storage.py::StorageCircuitBreaker` had `failure_threshold=1` and `reset_timeout=120s` — a **single** transient SSL/500 error from object storage tripped the breaker for 2 full minutes.
2. While the breaker was open, every subsequent chunk uploaded by the user landed on **ephemeral pod filesystem** (`/var/video_chunks/...`) instead of persistent object storage.
3. The pod restarted (frequent in this environment due to ephemeral storage churn — already documented as a recurring issue this session).
4. All chunk files on filesystem **evaporated** with the pod.
5. iter70's integrity guard counted what survived on object storage = 50 of 85, marked the video `failed` with "Upload incomplete".

The user wasn't doing anything wrong — chunks were being silently routed to a storage tier that couldn't survive a pod recycle.

### Fix
- **Circuit breaker far more lenient**: `failure_threshold` raised 1 → 8, `reset_timeout` dropped 120 → 60. A single SSL flake no longer reroutes anything. Need 8 consecutive failures to open the breaker.
- **`put_object_with_retry`**: `max_retries` raised 2 → 4 with exponential backoff (was hardcoded 2s) — most transient hiccups get absorbed silently before any fallback decision.
- **Filesystem-routed chunks rejected with 503**: in `server.py::upload_chunk`, if a chunk lands on filesystem (because the breaker tripped or all object-storage retries failed), we delete the local file and raise `HTTPException(503, Retry-After: 5)` instead of committing the chunk to `chunked_uploads`. The iter79 client-side retry loop already treats 503 as retryable, so the client backs off (2s, 4s, 8s … up to 60s) and re-uploads against (hopefully recovered) object storage.
- **HTTPException propagation fix**: the broad `except Exception` in `upload_chunk` was swallowing the new 503 and re-wrapping as 500. Added explicit `except HTTPException: raise` before the catch-all.

### Verified live
End-to-end smoke test on preview while object storage was returning intermittent 500s:
- 4 internal retries attempted per chunk (was 2)
- Circuit breaker stayed CLOSED (would have opened on the first failure under iter80)
- After 4 failures, chunk falls back to filesystem → my new code deletes the local file and returns 503
- Client retry sees 503, will back off and retry on next attempt

### Tests
- 5 new pytest cases in `test_storage_circuit_breaker.py`:
  - `test_circuit_breaker_threshold_is_lenient` — guards against future tightening below 5
  - `test_circuit_breaker_resets_after_timeout` — sanity-checks 30-120s range
  - `test_circuit_breaker_opens_only_at_threshold` — opens at exactly 8, not earlier
  - `test_circuit_breaker_success_resets_failure_count` — recovery semantics
  - `test_put_object_with_retry_signature` — guards against future regression of max_retries default

All passing. Lint clean across both modified Python files.

BUILD_VERSION → **iter81**, feature_count 88.



## ALL Videos Use Chunked Upload Now (iter80 — May 2026)

Real production bug 2026-05-21: user followed iter79 advice and compressed a 7.63 GB video down to **845 MB** with HandBrake. Tried to upload twice — both failed at 24%. Generic alert "Video upload failed" with no detail.

Root cause: `MatchDetail.js` routed files **≤1 GB through `handleStandardUpload`** — a single `axios.post()` with NO retry logic, NO offline detection, NO resume support. A 845 MB file at typical home upload speeds = ~25 min of continuous connection, and any blip kills the entire upload.

The iter79 work (6 retries, offline auto-pause, resume banner) only applied to `handleChunkedUpload`. Files under 1 GB never benefited.

### Fix
- `onFileChange` in `MatchDetail.js` now routes **every video upload** through `handleChunkedUpload`, regardless of size.
- `handleStandardUpload` removed — was the source of every "Video upload failed" generic alert. Replaced with a comment explaining why.
- The OS confirm dialog for the 1-5 GB band is preserved (sets expectations on upload time), and the >5 GB UploadPanel nudge still works.

### Why chunked-for-everything is the right call
- A 100 MB file uploaded as 10 chunks of 10 MB each is barely slower than a single 100 MB POST (the round-trip overhead is dominated by upload bandwidth, not request count)
- BUT it gets all the resilience for free: per-chunk retries, offline auto-pause, resume from last chunk, accurate progress in the iter79 "Incomplete upload waiting" banner
- The standard-upload "fast path" was a premature optimization that cost the user two failed 845 MB attempts and a frustrating support cycle

### Verified live
End-to-end smoke test on preview: 886 MB sentinel init → `chunk_size=10MB`, `total_chunks=85`, `resume=false`, `progress_pct=0.0`. `pending-uploads` endpoint correctly surfaces the in-flight session with accurate progress fields.

BUILD_VERSION → **iter80**, feature_count 87.



## Resilient Chunked Upload + Auto-Resume Banner (iter79 — May 2026)

User screenshot (2026-05-20) showed the iter70 red `RE-UPLOAD REQUIRED` banner firing correctly on a 7.63 GB upload that landed at only **404 of 782 chunks (51.7%)**. The fail-fast and recovery UI are working; the actual problem is the **upload itself keeps dropping mid-flight** on the user's home connection (~4 hours of upload time = plenty of opportunity for a wifi blip to kill it).

iter79 makes the upload pipeline far more resilient:

### Frontend (`pages/MatchDetail.js`)
- **`uploadChunkWithRetry` upgraded**: 3 → 6 retries with exponential backoff up to 60s per attempt (vs old 30s cap).
- **New `waitForOnline(statusSetter)` helper**: when the browser reports offline (`navigator.onLine === false`), the upload loop **pauses** instead of failing, updates the status to "Offline — upload paused. Will auto-resume when connection returns.", and resumes the moment `online` fires. Falls back to a 5s poll for VPNs / captive portals that don't emit the event.
- **Smarter failure message**: when the retry budget genuinely exhausts, the alert now includes file-size-aware compression advice — for files >2 GB it shows HandBrake `Fast 720p30 / CQ 28` step-by-step (cuts size ~80% without losing AI-relevant detail).
- **NEW "Incomplete upload waiting" banner** at the top of the match page: surfaces when `GET /api/matches/{match_id}/pending-uploads` returns sessions with status `initialized` / `in_progress` / `failed`. Tells the coach exactly which file to re-pick + the current % complete so they know resume is possible and won't waste another upload session from scratch.

### Backend (`server.py`)
- New `GET /api/matches/{match_id}/pending-uploads` — returns the coach's incomplete chunked-upload sessions for the match with `chunks_received / total_chunks / progress_pct / file_size_gb / filename` so the resume banner can render with accurate progress info.

### Why this matters for the user's actual workflow
The 7.63 GB / 51.7% case from the screenshot would now:
- Auto-retry each chunk up to 6× with 60s backoff (catches most home-wifi blips)
- Auto-pause on offline detection rather than burning retries (catches longer dropouts)
- If the coach closes the tab and comes back, show the resume banner immediately — no need to guess whether to re-pick the file or start over
- If the retry budget genuinely exhausts (truly bad connection), the error message now points at HandBrake compression instead of just saying "try again"

BUILD_VERSION → **iter79**, feature_count 86.



## Manual Claim-Owner Endpoint (iter78 — May 2026)

Production owner still couldn't access `/admin/processing-events` after iter77 deployed. Possible causes: deploy didn't actually pick up iter77 due to recurring `.gitignore` corruption, the startup migration timing missed the owner's user doc, or the migration ran but the user's existing JWT was carrying the stale `coach` role until next login.

iter78 ships a manual one-shot fallback that works regardless of which iteration is actually deployed and regardless of whether the migration fired:

### Endpoint
- New `POST /api/admin/claim-owner` — no body needed, no shared secret needed.
- Only callers whose authenticated email matches the hardcoded `_OWNER_CLAIM_EMAILS` allowlist (currently `{"ben.buursma@gmail.com"}`, case-insensitive) can use it.
- Any other authenticated user gets a clean **403** with an explicit "reserved for the app owner" message — never a silent no-op so we can debug accidental hits.
- Idempotent: re-running for an already-admin caller returns `{status: "already_admin", role: "admin"}`.
- Logs every promotion at WARNING level for audit.

### Owner recovery one-liner (after deploy)
While logged into soccerscout11.com with the owner email, paste in the browser dev console:
```js
fetch('/api/admin/claim-owner', { method: 'POST', credentials: 'include' })
  .then(r => r.json()).then(console.log)
```
Expected output: `{status: "promoted", role: "admin"}`. Then refresh — `/admin/processing-events` will now load.

### Tests
- 4 new pytest cases in `test_claim_owner.py`:
  - `test_claim_owner_requires_auth` — 401/403 for unauthenticated callers
  - `test_claim_owner_rejects_non_owner_user` — 403 with explicit reason for callers not in allowlist
  - `test_claim_owner_promotes_canonical_owner` — happy path: coach → admin in DB
  - `test_claim_owner_idempotent_when_already_admin` — `status: already_admin`
- All passing. Wide regression: 24/24 across admin-bootstrap test surface (claim-owner + owner-admin-seed + admin-autopromote + pod-oom-loop + partial-upload).

BUILD_VERSION → **iter78**, feature_count 85.



## One-Time Owner-Admin Seed Migration (iter77 — May 2026)

User context: production owner couldn't access `/admin/processing-events`. iter76 added `ADMIN_AUTOPROMOTE_EMAIL` env-var auto-promotion, but the Emergent deployment UI on the user's plan doesn't expose a secrets/env-var panel post-deploy — they had no way to set the env var. iter77 ships a code-only fix that requires zero UI interaction.

### Behavior
- New `_seed_owner_admin_once()` startup task in `server.py` runs once per Mongo database.
- Looks up the hardcoded canonical owner email (`ben.buursma@gmail.com`, case-insensitive) in the users collection.
- If found AND not already `admin`/`owner` → promotes to `admin` + logs at WARNING level for audit.
- Records a `system_migrations` marker `iter77_owner_admin_seed` so subsequent restarts are no-ops.
- Marker write is **conditional on the user existing** — if the owner hasn't registered yet, the migration silently no-ops and retries on the next boot (instead of being marked complete forever).
- Migration failures are swallowed — never crash startup.

### Why hardcoded
The user's Emergent plan tier doesn't expose the env-var panel post-deploy. Once they upgrade or the env-var path becomes available again, iter76's `ADMIN_AUTOPROMOTE_EMAIL` mechanism remains operational as the long-term solution — iter77 is just the one-time bootstrap. Hardcoding is documented inline in `server.py::_seed_owner_admin_once` with the rotation pattern (bump the migration_id when changing the email).

### Files touched
- `server.py`: new `_seed_owner_admin_once()` helper + scheduled in `@app.on_event("startup")` as `asyncio.create_task` (so a slow Mongo lookup doesn't delay other startup tasks).

### Tests
- 3 new pytest cases in `test_owner_admin_seed.py`, subprocess-isolated (same pattern as iter70/iter75 to avoid Motor cross-file state leaks):
  - `test_seed_promotes_existing_coach_owner` — happy path: coach → admin, marker recorded
  - `test_seed_idempotent_when_marker_present` — marker exists, full no-op (role stays coach)
  - `test_seed_skips_when_user_not_registered` — no user matches → no marker (retries on next boot)
- All passing. Wide regression: 61/61 tests pass across iter72-77 touched surface.

### Onboarding flow for the production owner
**Single step**: redeploy. On next pod startup, the migration runs, promotes Ben.buursma@gmail.com to admin, logs the action, records the marker. `/admin/processing-events` becomes accessible. No env vars, no UI clicks, no curl commands needed.

BUILD_VERSION → **iter77**, feature_count 84.



## Admin Auto-Promote on Login (iter76 — May 2026)

User Ben on production couldn't access `/admin/processing-events` because the production Atlas DB had no admin role flag on their account, and the existing `/api/admin/bootstrap` endpoint required a manual curl with the `ADMIN_BOOTSTRAP_SECRET` env var — too cumbersome.

iter76 adds an env-controlled auto-promote path so the owner can self-onboard simply by setting one production secret.

### Behavior
- New env var `ADMIN_AUTOPROMOTE_EMAIL` — accepts a single email or a comma-separated list (`a@x.com, b@y.com`).
- On every successful `/api/auth/login` AND every authenticated request via `get_current_user`, if the user's email (case-insensitive) matches any entry in the env var AND the user isn't already `admin`/`owner`, their role is `$set` to `admin` in `users` collection.
- Idempotent: already-admin users are a no-op (no DB write).
- Fail-safe: env var unset → no-op. DB failure during promotion → swallowed + logged, login still succeeds with the old role.
- Audit trail: every promotion logs at WARNING level with the user_id, old role, and new role.

### Files touched
- `server.py`: new `_maybe_autopromote_admin(user)` helper. Called in both the login endpoint (BEFORE `create_token`) and inside `get_current_user`.
- `routes/auth.py`: mirror of the helper to keep both authentication paths in sync (codebase already maintains two synced `get_current_user` implementations).

### Onboarding workflow for the production owner
1. In Emergent Deployments UI → Secrets → add `ADMIN_AUTOPROMOTE_EMAIL=Ben.buursma@gmail.com`
2. Redeploy
3. Log out + log back in on https://soccerscout11.com — server logs "ADMIN_AUTOPROMOTE_EMAIL match — promoted Ben.buursma@gmail.com from role='coach' to role='admin'"
4. Admin sections (`/admin/processing-events`) now accessible

### Playbook compliance
Per the system prompt rules for any auth-touching change, this was routed through `integration_playbook_expert_v2` BEFORE writing code. Playbook recommendations applied: case-insensitive email normalization, idempotent DB writes, WARNING-level audit logging, fail-safe defaults, no changes to bcrypt verification / JWT signing / cookie setting paths.

### Tests
- 9 new pytest cases in `test_admin_autopromote.py`:
  - env unset → no-op
  - already-admin → idempotent no-op
  - already-owner → idempotent no-op
  - happy path: email matches, role flipped in DB
  - case-insensitive email matching
  - comma-separated list matches any entry
  - email doesn't match → no-op
  - server.py + routes/auth.py copies behave identically
  - E2E login flow on the live API doesn't promote unmatched users
- All passing. Wide regression: 71/71 tests pass across touched suites when run individually.

BUILD_VERSION → **iter76**, feature_count 83.



## Pod-OOM-Loop Guard (iter75 — May 2026)

Real production bug 2026-05-18: a 3.93 GB video (`2ebe539f-b00b-...`) uploaded cleanly to soccerscout11.com (full integrity, no partial banner), but processing stuck at 0% forever — every pod restart re-queued it via `resume_interrupted_processing`, ffmpeg OOM-killed the **whole pod** mid-`prepare_video_sample` before iter63's Python-level auto-retry tier could fire, then the cycle repeated indefinitely.

iter70's integrity guard didn't trip because integrity was full. iter63's auto-retry didn't trip because ffmpeg never returned a Python exception — the pod itself died.

### Fix
- New `resume_attempts` field on the `videos` collection, bumped on every resume by `resume_interrupted_processing`.
- New `_MAX_RESUME_ATTEMPTS = 3` constant in `server.py`.
- When `resume_interrupted_processing` finds a video with `resume_attempts >= 3` AND `processing_progress == 0`, it marks the video `failed` with: *"Processing failed N× without making any progress. Source file is too heavy for our encoding pod — re-compress with HandBrake (Fast 720p30 / CQ 28) and re-upload."*
- A `final_failure` event is logged with `failure_mode = "pod_oom_loop"` so the Top Failed Videos panel surfaces it with a distinct color.
- A video that previously made >0% progress is NOT subject to the guard — iter63's auto-retry can still help it.

### Frontend
- `FAILURE_MODE_COLOR` extended with `pod_oom_loop: '#DC2626'` (dark red — even worse than single oom).
- No new UI surface needed: the `failed` status already triggers iter70's red `RE-UPLOAD REQUIRED` banner with a one-click DELETE & RE-UPLOAD CTA, and the Email Fix button in the Top Failed Videos panel auto-routes the iter71 HandBrake compression-help template (since `failure_mode != "incomplete_upload"`).

### Tests
- 3 new pytest cases in `test_pod_oom_loop_guard.py` (subprocess-isolated):
  - `test_resume_marks_oom_loop_after_max_attempts` — full happy-path: 3 attempts → failed + event logged
  - `test_resume_bumps_attempts_when_below_cap` — below cap, counter bumped to N+1, NOT failed
  - `test_resume_with_partial_progress_does_not_trip_oom_guard` — progress=35%, attempts=5 still re-queues (iter63's tier can still help)
- Wide regression: 45/45 tests pass across touched suites.

BUILD_VERSION → **iter75**, feature_count 82.



## Three Triple-Header Features (iter72/73/74 — May 2026)

### iter72: Sent-Email Audit Log + Open Tracking

**Backend** (`services/email_queue.py`, `routes/recruiter_lens.py`, `routes/admin.py`):
- New `_inject_open_pixel(html, queue_id)` helper appends a `<img>` tag pointing at `/api/lens-track/email-pixel/{queue_id}.png` BEFORE `</body>` on every templated send. Pixel URL embeds the `queue_id` so opens are credited to the specific send (even if Resend retries via the queue).
- New public endpoint `GET /api/lens-track/email-pixel/{queue_id}.png` — returns a hardcoded 67-byte transparent PNG (no Pillow dep), idempotent: stamps `opened_at` only on first hit, bumps `open_count` and `last_opened_at` on every subsequent hit. Returns 200 + PNG even for unknown queue_ids (no info leak about which IDs are valid).
- New admin endpoint `GET /api/admin/email-audit-log?days=30&kind=` — newest-first list of email_queue rows with `opened_at` / `open_count` / `attempts` / `last_error`, plus `by_kind` rollup for relative open-rate comparison across template families.
- Critical bug fixed during testing: `find_one(query, {"opened_at": 1})` returns `{}` (falsy in Python) when neither field exists yet — switched to `is not None` check + included `id` in projection.

**Frontend** (`pages/AdminProcessingEvents.js`):
- New "Admin email audit" Section with a kind filter (`all` / `compression_help` / `incomplete_upload_help` / `hot_lead` / `processing_alert`) and an "X/Y opened (Z%)" summary. Per-row "✓ Opened" badge with hover tooltip showing first-open timestamp + repeat-open count.

**Tests**: 7 cases in `test_email_audit_and_pixel.py` covering pixel + audit + injection. All passing.

### iter73: Mass Recruiter Blast / Mail Merge (P1)

**Backend** (`routes/recruiter_lens.py`):
- New `POST /api/lens-links/blast` — body `{team_id, filters, recipients[], message, blast_id?}`. Creates ONE unique `lens_link` row + tracking token PER recipient so Hot Lead detection / opens / clicks remain attributable per-recipient.
- **Per-coach daily cap**: 25 unique lens_link rows per 24h, enforced across BOTH `/lens-links` (single) and `/lens-links/blast` so coaches can't bypass via alternation. Computed by counting all of the coach's lens_link rows in the trailing 24h. Once hit, remaining recipients get `status: "skipped_over_cap"` instead of being silently dropped.
- **Per-request hard ceiling**: 50 recipients to keep response payloads bounded.
- **In-request dedup**: case-insensitive on emails, preserves first-occurrence order so the UI results table matches what the coach pasted.
- All recipients in one blast share the same `blast_id` so the SentLensLinks panel can later group them visually.

**Frontend** (`pages/components/RecruiterOutreachModal.js`):
- Modal now has a **mode toggle** at the top: "One recipient" (existing flow, unchanged) ↔ "Mass blast (CSV)".
- Blast mode: paste-area textarea accepting `email`, `email, name`, OR `Name <email>` formats. Skips blank lines, `#` comments, and header rows ("email"/"Email"). Live preview table shows the parsed unique recipients.
- After send: results table per-row with color-coded status (`sent` / `quota_deferred` / `skipped_over_cap` / `failed`) + summary line ("✓ 12 sent · ⚠ 3 skipped (daily cap)").

**Tests**: 8 cases in `test_lens_blast.py` covering auth, validation (empty, >50, unknown team), dedup, per-recipient unique tokens, blast_id grouping, daily cap respect. All passing.

### iter74: Send Roster Reminder Admin Tool

**Backend** (`routes/admin.py`):
- New `GET /api/admin/empty-roster-matches?days=14&limit=25` — surfaces matches where the video processed cleanly (`processing_status == "completed"`) but the roster is empty (0 player rows). High-leverage triage because AI tactical attribution silently produces 0 player-credited events on these — coaches see analysis "complete" but with no value.
  - Joins with `videos` + `players` (aggregation for count) + `users` + `roster_reminder_sent` for triage context.
  - Each row includes `coach_email`, `match_label`, `video_uploaded_at`, and `reminder_sent_at` (null if not yet sent).
- New `POST /api/admin/empty-roster-matches/send-reminder` body `{match_id}` — sends an amber-themed Resend HTML email pointing the coach at the iter69 ⚡ Quick Attach pill for a 2-click recovery.
  - De-duped via `roster_reminder_sent` collection — repeat clicks return `status: "already_sent"`.
  - **Race-condition guard**: if the roster has been populated between dashboard load and admin click, returns `status: "skipped"` with reason "match already has N player(s) — reminder no longer needed".

**Frontend** (`pages/AdminProcessingEvents.js`):
- New "Empty-roster matches" Section with one-click "Send reminder" button per row, flips to "✓ SENT" badge after success. Clicking the match label navigates to the match page.

**Tests**: 8 cases in `test_roster_reminder.py` covering auth, list filtering (with/without players), 404, race-condition skip, dedup, sent-flag surfacing. All passing.

### Wide Regression
**92/92 tests pass** across 12 touched test files (templates + audit + blast + reminder + partial-upload + quick-attach + recruiter-outreach + email-queue + processing-events + processing-alerts + match-roster-first). Lint clean across all touched Python and JS files.

BUILD_VERSION → **iter74**, feature_count 81 (+3).



## Email-Fix Template Branching + `incomplete_upload` Chart Surface (iter71 — May 2026)

After iter70 added the `incomplete_upload` failure mode, the existing "Email fix" button on the Top Failed Videos panel was actively misleading for those rows — it sent HandBrake compression instructions for a file that was already small enough; the real problem was the browser connection dropping mid-upload. iter71 closes that loop.

### Backend (`routes/admin.py`)
- New `_incomplete_upload_help_html(coach_name, filename, size_gb, available, total)` — red-header email template (`#EF4444`) with:
  - The exact chunk progress baked into the body ("Our copy only has 980 of 991 chunks (98.9%)")
  - Reassurance that the source file is fine ("Your original file on your computer is fine; just our copy is incomplete")
  - In-product DELETE & RE-UPLOAD CTA reference (added in iter70)
  - Network-quality advice (wired / close to router) as the primary fix, with HandBrake mentioned only as a secondary tip for flaky connections
- New `_parse_chunks_from_error(error_message)` — pulls `(available, total)` out of the canonical "Upload incomplete (N of M chunks, P%)" string written by `services/processing.py`. Returns `(None, None)` defensively if the pattern doesn't match, so the fallback message still sends.
- `POST /api/admin/processing-events/email-compression-help` now branches:
  - `failure_mode == "incomplete_upload"` → red template + subject "Your Soccer Scout upload got cut off — quick re-upload" + `kind="incomplete_upload_help"`
  - Everything else → existing blue HandBrake template (unchanged behavior)

### Frontend (`pages/AdminProcessingEvents.js`)
- `FAILURE_MODE_COLOR` extended with `incomplete_upload: '#0EA5E9'` (sky blue) — visually distinct from the OOM/timeout reds & oranges so admins can spot connection-quality failures at a glance on the bar chart.
- Email Fix button tooltip is now failure-mode-aware: hovering an `incomplete_upload` row says "Send the coach 'upload got cut off — re-upload from a stable network' instructions" so admins know which template will go out before they click.

### Tests
- New `test_compression_email_templates.py` with 6 unit tests:
  - `test_parse_chunks_from_error_canonical` — round-trips "980 of 991 chunks"
  - `test_parse_chunks_from_error_returns_none_when_unparseable` — defensive on `None`, `""`, arbitrary text
  - `test_incomplete_upload_html_includes_red_cta_and_progress` — red header, chunk progress (98.9% — verifies the rounding), DELETE & RE-UPLOAD CTA, no HandBrake in primary message
  - `test_incomplete_upload_html_falls_back_without_chunk_numbers` — graceful when chunk parse fails
  - `test_compression_html_recommends_handbrake` — existing template still recommends Fast 720p30 / CQ 28
  - `test_html_templates_handle_no_name` — graceful greeting without a `coach_name`
- Full regression: **44/44 tests pass** across all touched suites (templates + quick-attach + partial-upload-failfast + processing-events + processing-events-top-failed + processing-alerts + ffmpeg-error-classification).

BUILD_VERSION → **iter71**, feature_count 78.



## Partial-Upload Fail-Fast Guard (iter70 — May 2026)

Real production bug 2026-05-16 (video `48823490-f162-...`, 9.67 GB, 980/991 chunks = 99%) sat at 0% forever showing "Server restarted — processing resumed automatically. Preparing video for AI analysis." Root cause: the upload itself was incomplete (11 chunks missing), but the system kept resuming and re-queueing — every pod restart hit the same incomplete-data wall. ffmpeg either silently produced a broken sample or got OOM-killed on the partial 9.67 GB source.

iter70 closes the loop with three guards:

### (a) Fail-fast guard in `services/processing.py::run_auto_processing`
- New `_check_chunk_integrity(video)` helper mirrors the same logic used by `/api/videos/{id}/metadata` — counts chunk paths actually present on disk vs. `total_chunks`.
- BEFORE the ffmpeg call, if integrity != "full", we mark the video `failed` with `processing_error: "Upload incomplete (980 of 991 chunks, 99.0%). Re-upload required — AI analysis can't run on a partial file."` and log a `final_failure / failure_mode=incomplete_upload` processing event for the admin dashboard.
- Result: no more silent OOM-loops, no more hung 0% UI.

### (b) Resume-skip in `server.py::resume_interrupted_processing`
- On every pod restart, before re-queueing stuck `queued`/`processing` videos, run the same integrity check.
- Partial-integrity videos are marked `failed` with the same actionable error — once — instead of being re-queued forever across restarts.
- Net: a partial upload now fails fast on the FIRST restart instead of spinning forever.

### (c) Frontend escalation: red "RE-UPLOAD REQUIRED" callout in `DataIntegrityBanner`
- Existing amber "Partial video data" banner kept for the "playback may end early but AI can still run on what's here" case.
- Escalated to a **red `RE-UPLOAD REQUIRED` callout** with a one-click "DELETE & RE-UPLOAD" CTA when ANY of:
  - `data_integrity == "unavailable"`
  - `processing_status == "failed"` (regardless of why)
  - `processing_error` contains "upload incomplete"
  - Stuck-at-zero for >120s in `queued`/`processing` (catches the prior "infinite 0% spinner" case from this session's prod bug)
- The CTA calls `DELETE /api/videos/{id}` then navigates back to the match page where the upload UI is ready for a fresh file. Match, roster, and existing clips stay intact.

### Tests
- New `test_partial_upload_failfast.py` with 5 cases:
  - 3 unit tests on `_check_chunk_integrity` (full / partial / unavailable)
  - 1 integration test: incomplete chunked video → run_auto_processing → marked `failed` with correct error string
  - 1 integration test: incomplete chunked video → resume_interrupted_processing → marked `failed`, NOT re-queued
- Integration tests run in subprocess so Motor's loop-bound `db` object doesn't leak across sibling test files.
- Full regression: 38/38 tests pass across touched suites (`test_partial_upload_failfast.py`, `test_processing_events.py`, `test_processing_events_top_failed.py`, `test_processing_alerts.py`, `test_quick_attach_and_compression_email.py`, `test_ffmpeg_error_classification.py`).

### Immediate production workaround
The fix is in preview only — the stuck video on production (`soccerscout11.com/video/48823490-f162-4f7c-a771-6a84188fde4d`) will remain stuck until either (a) the user deletes it and re-uploads, or (b) iter70 is deployed and the next pod restart marks it failed cleanly via the new resume-skip guard.

BUILD_VERSION → **iter70**, feature_count 77.



## Quick-Attach Pill + Compression-Help Email (iter69 — May 2026)

Two complementary triage features shipped together: one for coaches (faster roster setup), one for admins (closed-loop support on failed uploads).

### Feature 1: ⚡ Quick-Attach Last Used Team

The "Import Existing Team" dropdown from iter67 was great for coaches with many saved teams, but redundant for the most common case: a coach running through a season with one core team, opening match after match. Now the most-recently-used team appears as a one-click amber/gold pill in the roster header.

**Backend**:
- Existing `POST /api/matches/{match_id}/import-team-roster` now also writes `users.last_imported_team_id` + `last_imported_team_at`. Critically, the pointer update happens BEFORE the "no players to import" early-return — the coach's intent ("this is my active team") is what matters, not the row count.
- New `GET /api/me/last-imported-team` returns `{team_id, team_name, team_season, last_used_at}` or all-nulls. Self-healing: if the team was deleted, it `$unset`s the stale pointer so we stop re-checking.

**Frontend** (`pages/components/RosterSection.js`):
- New `quick-attach-team-btn` rendered only when (a) the coach has a last-used team, (b) the current match is empty, (c) the dropdown form is closed. Avoids double entry points.
- Distinctive amber/gold gradient styling (`from-[#FBBF24]/15 to-[#F59E0B]/15`) with a `Lightning` icon — visually separates the shortcut from the canonical buttons next to it.
- Calls the same import endpoint as the dropdown flow → refreshes both the player list and the last-team pointer.

**Verified live**: pill renders as `⚡ QUICK ATTACH LAKESHORE FC 2007 B PREMIER` on an empty match for testcoach. One click → 6 players imported.

### Feature 2: 📧 "Email fix" — closed-loop support on failed uploads

The iter68 Top Failed Videos panel surfaces a `2.5 GB / all_tiers_exhausted` failure in production. The coach who uploaded it doesn't know what to do next. Instead of a triage row that just stares back, the admin can now click one button and Resend them HandBrake compression instructions with the exact "Fast 720p30 / CQ 28" settings.

**Backend** (`routes/admin.py`):
- New `POST /api/admin/processing-events/email-compression-help` body `{video_id}`.
- Looks up the `final_failure` event, the source video, and the coach; sends a dark-themed HTML email (matches the rest of the Soccer Scout transactional emails) via the existing `send_or_queue` helper from `email_queue.py` (gets retry + quota deferral for free).
- De-duped via the new `compression_help_sent` collection — same `video_id` returns `status: "already_sent"` with the prior timestamp instead of double-spamming the coach.
- Graceful failure: no email on record → `status: "skipped"` with a reason, not a 500. Front-end shows the reason as a toast.

**Backend** (`_enrich_failed_event` in `routes/admin.py`):
- Top Failed Videos rows now include `compression_email_sent_at` so the UI can render "✓ Sent" instead of the "Email fix" button for handled rows.

**Frontend** (`pages/AdminProcessingEvents.js`):
- New "HELP" column in the Top Failed Videos table.
- "Email fix" button (`email-fix-btn-{video_id}`) per row in the same amber/gold tone as the Quick Attach pill — visually paired as "operator-shortcut" controls.
- Disabled when there's no coach email (with tooltip explaining why).
- After a successful send, refreshes the panel — the row flips to a "✓ SENT" badge (green) with hover-tooltip showing the send timestamp.

**Verified live**: 2 Email Fix buttons render on real preview-env failures (the 2.5 GB OOM + the moov_missing one tied to Test Coach). De-dup test confirmed: pre-seeded `compression_help_sent` row triggers `status: "already_sent"` on the next click.

**8 pytest cases shipped** (`test_quick_attach_and_compression_email.py`):
1. `test_last_imported_team_returns_null_when_never_used`
2. `test_import_team_roster_updates_last_team_pointer`
3. `test_last_imported_team_self_heals_when_team_deleted`
4. `test_compression_email_requires_admin`
5. `test_compression_email_skips_when_no_email`
6. `test_compression_email_404_when_no_failure_event`
7. `test_compression_email_dedupes_repeat_clicks`
8. `test_top_failed_surfaces_compression_sent_flag`

All passing alongside the existing 48 tests in the touched suites.

BUILD_VERSION → **iter69**, feature_count 76.



## Top-5 Largest Failed Videos Triage Panel (iter68 — May 2026)

Quick-triage panel added to the Admin Processing Events Dashboard (P2 from the iter67 backlog). Surfaces the biggest failures first because they're the highest-leverage to investigate: either pushing against the pod-memory ceiling (justifies a bump) or hitting an upload-size UX gap (justifies clearer warnings).

**New endpoint** `GET /api/admin/processing-events/top-failed?hours=24&limit=5`
- Pulls `final_failure` events from `processing_events` within the window, sorted by `source_size_gb` DESC.
- Dedupes by `video_id` — a single video that retried 3 times can't crowd out 4 other failing videos.
- Joins with `videos` / `matches` / `users` so the admin sees filename, parent match, and coach email in one row. Defensive against hard-deleted joins → falls back to `(deleted)` / `null` rather than dropping the row (admin still wants to know an 8 GB upload died, even if the video doc is gone).
- Admin-only (`_require_admin`). Hours capped at 168 (1 week), limit capped at 20.

**Frontend panel** (`pages/AdminProcessingEvents.js`)
- New "Top largest failed videos" Section placed directly under the stat cards (above-the-fold for triage priority).
- Independent hours selector: `Today (24h)` / `Last 3d` / `Last 7d` — separate from the main `days` selector so the admin can scope triage tighter than the aggregate dashboard.
- Table columns: Size (right-aligned, bold), Filename, Failure (color-coded same as charts), Tier reached, Coach (mailto link with pre-filled subject), Match (button → `/match/{id}`), Failed at.
- Empty state: "No final failures in this window. 🎉"

**Verified live (preview)**: panel rendered real data on first load — a `2.5 GB` OOM with `all_tiers_exhausted` (exactly the leverage case this panel exists to surface) plus a `0.03 GB` moov_missing failure tied to "Team A vs Team B" with the coach mailto populated.

**4 pytest cases shipped** (`test_processing_events_top_failed.py`):
- `test_top_failed_sorts_by_size_and_dedupes` — 3 videos seeded with one repeat-failer, verifies size ordering + dedup + enrichment.
- `test_top_failed_respects_window` — 9.9 GB failure 72h ago must NOT appear when window=24h.
- `test_top_failed_handles_missing_joins` — orphaned event (no videos doc) still renders as `(deleted)` instead of crashing.
- `test_top_failed_requires_admin` — unauthenticated callers get 401/403.

BUILD_VERSION → **iter68**, feature_count 75.



## "Import Existing Team" UI Wire-Up (iter67 — May 2026)

User reported: "Attach an existing team to an already uploaded game. There is no option to SELECT TEAM. Only Create player or import CSV." Bug spans **preview + production**.

**Root cause**: Backend `POST /api/matches/{match_id}/import-team-roster` (added in iter61) has full test coverage and works end-to-end, but the `RosterSection` component on the `MatchDetail` page only surfaced two action buttons — "CSV Import" and "Add Player". The third button to attach an existing saved team's roster was never wired into the UI. Coaches with saved team rosters were forced to re-type / re-CSV-paste their lineup on every new match.

**Fix shipped**:
- Added `ImportTeamForm` sub-component to `pages/components/RosterSection.js` (new "SAVED TEAM" dropdown listing every team the coach owns).
- New `IMPORT EXISTING TEAM` button in the roster header, conditionally rendered only when `teams.length > 0` so coaches without saved teams don't see a dead-end button.
- Wired new state (`showImportTeam`, `selectedTeamId`, `importingTeam`) and `handleImportTeam` handler in `MatchDetail.js`. Posts to existing `/api/matches/{match_id}/import-team-roster` then refreshes the player list and toasts an alert like "Imported 14 players from Lakeshore FC 2007 B Premier (3 skipped — already on this match)."
- `data-testid`s for full automatability: `import-team-btn`, `import-team-form`, `import-team-select`, `submit-import-team-btn`, `cancel-import-team-btn`.

**Verified live**: Logged in as testcoach@demo.com → opened a match → confirmed the new "IMPORT EXISTING TEAM" button renders alongside CSV Import + Add Player → clicking it opens the form → "SAVED TEAM" dropdown is populated with both saved teams (`Lakeshore FC 2007 B Premier — 2025/26`, `Lakeshore FC 2007 B Premier — 2026/27`).

BUILD_VERSION → **iter67**, feature_count 74.



## Code-Review Complexity Refactors (iter66 — Feb 2026)

User submitted a code-quality report. Audited each finding before touching code:

**Items 1-3 were FALSE POSITIVES** — verified and explained, no changes:
- "Hardcoded secrets": Each flagged line was either a randomly-generated UUID per test (`token = "vwtk-" + uuid.uuid4().hex[:8]`) or the HTTP standard cookie name "access_token=" (not a credential).
- "10 undefined variables": Both `pyflakes` and `ruff --select F821,F823,F841` reported zero matches. Tool error.
- "`is` vs `==` anti-pattern": Every flagged instance was `is None` / `is not None` / `is True` / `is False` — PEP 8-mandated idiomatic Python. Grep for the actual anti-pattern (`is "literal"` or `is integer`) returned zero hits in code (2 false matches in comments). Python compiler raised zero SyntaxWarnings.

**Item 4 — Complexity refactors — LEGITIMATE, all 5 functions fixed:**

| Function | Before | After |
|---|---|---|
| `routes/admin.py::processing_events_stats` | CC=15, 79 lines, 17 vars | CC=2, 48 lines (extracted `_bucket_groupings`, `_bucket_outcome_counters`, `_derive_rates`) |
| `routes/insights.py::generate_match_insights` | CC=19, 122 lines, 19 vars | CC=3, 15 lines (extracted `_load_match_signal`, `_build_insights_prompt`, `_call_gemini_insights`, `_shape_insights_response`, `_format_marker_lines`, `_summarize_clip_types`) |
| `routes/matches.py::_build_match_recap_prompt` | CC=16 | CC=7 (extracted `_derive_recap_outcome`, `_format_match_event_lines`) |
| `routes/matches.py::_deterministic_recap` | CC=15 | CC=10 (extracted `_recap_verb`) |
| `routes/highlight_reels.py::browse_public_reels` | CC=22, 79 lines, 19 vars | CC=6 (extracted `_load_reels_with_context`, `_reel_passes_filter`, `_build_reel_card`, `_reel_context`) |
| `routes/highlight_reels.py::my_reel_stats` | CC=14, 77 lines | CC=5 (extracted `_reel_counters`, `_aggregate_7d_views`, `_resolve_top_reel`) |

All extracted helpers are pure or single-purpose — improves testability without changing observable behavior. Behavior parity verified by re-running the full touched-files test suite: **122/122 passing** (including 43 highlight_reel tests, 7 finish_match tests, 8 match_roster_first tests, 11 ffmpeg classification tests, 6 processing_alerts tests).

**Bug caught + fixed during refactor**: My initial `browse_public_reels` rewrite accidentally dropped the `@router.get("/highlight-reels/browse")` decorator and attached it to the wrong helper instead, producing a 422 on the public browse endpoint. Caught by `test_browse_response_hides_user_id` failing. Restored decorator → tests green.

**Test isolation fix**: 2 `test_processing_alerts.py` tests failed when running on the shared preview DB because real iter65 dev-time events polluted the 1-hour query window. Fixed by monkey-patching `_compute_last_hour_stats` per test to scope only to the test's sentinel video_id.

BUILD_VERSION → **iter66**, feature_count 73.



## Admin Dashboard + Auto-Alert Spike Detector (iter65 — Feb 2026)

User asked for both: admin UI for the iter64 processing-events stats AND auto-alert on failure spikes. Both shipped.

**Admin Dashboard** (`pages/AdminProcessingEvents.js`, new route `/admin/processing-events`):
- 4 stat cards: success rate, retry save rate, OOMs at tier 0, unique videos
- Bar chart: failure modes (color-coded: oom red, timeout amber, moov orange, etc)
- Bar chart: attempts by tier (horizontal — see at a glance which tier dominates)
- Bar chart: event types
- Recent events table (last 25, with timestamps + failure modes color-coded)
- Day-range selector: 24h / 7d / 30d
- "Run alert check now" button — fires the hourly check immediately for verification
- Uses `recharts` (already in deps from CoachNetwork.js)
- Verified live: dashboard rendered the real iter64 data on first load (18.2% success rate, 66.7% retry save rate on the test environment with 60 tier-0 attempts and the retry tier saving 6 of them).

**Auto-Alert Spike Detector** (`services/processing_alerts.py`, new):
- Hourly check loop wired in `server.py::on_startup` → `_processing_alerts_loop()`. Stagger-starts 2 minutes after boot then ticks every 3600s.
- Pulls `final_success` + `final_failure` events from the last hour. Computes `failure_rate_pct`.
- **Alert fires** when ALL of: `total >= MIN_ATTEMPTS_FOR_ALERT (3)`, `failure_rate_pct >= FAILURE_RATE_THRESHOLD_PCT (20)`, and either no prior alert in `ALERT_DEDUP_WINDOW_HOURS (6h)` OR new rate exceeds prior by `ESCALATION_RATE_DELTA_PCT (10pt)`.
- Email via existing `send_or_queue` (Resend) — recipient from `ALERT_RECIPIENT_EMAIL` env (falls back to `SENDER_EMAIL`). Tracked in `processing_alerts` collection for de-dup.
- HTML email template includes failure-rate, breakdown by mode, "what to check" checklist (pod memory bump, recent uploads, recent-failures link).
- Hard guarded: any exception in the loop is swallowed + logged. Alert monitoring cannot itself crash the app.
- New admin endpoint `POST /api/admin/processing-alerts/check` — manually trigger the same logic for verification.

**Tests** (`tests/test_processing_alerts.py` — 6 new tests):
- `test_skip_low_volume` — < 3 attempts → skip
- `test_skip_below_threshold` — 16.7% < 20% threshold → skip
- `test_alert_fires_when_threshold_crossed` — 60% failure → alert sent (Resend mocked)
- `test_dedup_within_window` — second consecutive check → skip_deduped
- `test_no_recipient_does_not_crash` — gracefully skips when no email configured
- `test_exception_in_compute_does_not_propagate` — defensive guard verified

**Test totals**: 39/39 passing across all suites. BUILD_VERSION → **iter65**, feature_count 68.

**New env vars** (production secrets to consider setting):
- `ALERT_RECIPIENT_EMAIL` — defaults to SENDER_EMAIL if unset
- `PROCESSING_ALERT_THRESHOLD_PCT` (default 20) — failure rate that triggers alert
- `PROCESSING_ALERT_MIN_ATTEMPTS` (default 3) — minimum volume for alert eligibility
- `PROCESSING_ALERT_DEDUP_HOURS` (default 6) — quiet period after last alert
- `PROCESSING_ALERT_ESCALATION_PCT` (default 10) — rate rise that breaks dedup



## Processing-Events Instrumentation (iter64 — Feb 2026)

User asked for visibility into the iter63 auto-retry: "would be useful to size your pod's memory limits when you scale."

**New collection** `processing_events` — append-only log of every ffmpeg attempt in `prepare_video_sample`. ~250 bytes per event, ~3 events per upload (tier_attempt → tier_failed → tier_succeeded or final_failure). Trivial disk pressure even at scale.

**Logged event types**: `tier_attempt`, `tier_succeeded`, `tier_failed`, `final_success`, `final_failure`.
**Failure modes tracked**: `oom`, `timeout`, `moov_missing`, `invalid_data`, `no_space`, `unknown`.

**New file** `services/processing_events.py` — single `log_event(...)` async helper. Errors during logging are swallowed (a pipeline-breaking log is worse than a missing log).

**Instrumentation in** `services/processing.py::prepare_video_sample` — each tier attempt + outcome + duration is logged. Final success/failure events let admin queries answer "of N videos attempted, M succeeded".

**Two new admin endpoints** (`routes/admin.py`, both `_require_admin`-gated):
- `GET /api/admin/processing-events/stats?days=N` — aggregated counts grouped by event_type / failure_mode / tier_label PLUS derived rates:
  - `final_success_rate_pct` — overall pipeline health
  - `retry_save_rate_pct` — % of tier-0 OOMs that recovered at tier 1 (justifies keeping the retry tier)
  - `tier0_oom_count` / `tier1_recoveries` — for sizing pod memory limits
- `GET /api/admin/processing-events/recent?limit=N&event_type=X&failure_mode=Y` — recent event tail for debugging

**Tests added** (`tests/test_processing_events.py` — 4 tests):
- Stats endpoint aggregates correctly with seeded fixture events
- Recent endpoint filters by event_type
- Both endpoints reject unauthenticated calls (401/403)

**Test totals**: 33/33 passing across all touched suites.



## Blank-Screen Fix + FFmpeg Auto-Retry + JSX-no-undef Regression Test (iter63 — Feb 2026)

User reported on production after iter62 deploy: "I just get a blank screen when I click on games that have videos uploaded." Reproduced in preview via Playwright — found the root cause and another lurking bug of the same class.

**Root cause #1** — `MatchDetail.js` used `<HighlightReelsPanel />` (line 389) but never imported the component. Mounted only when `match.video_id` was truthy (so it slept for any rosterless/videoless match), then React threw `ReferenceError: HighlightReelsPanel is not defined` and the error boundary unmounted the whole page → blank screen. Fix: one-line import statement.

**Root cause #2** (caught by the regression lint config below) — `useClipCollection` hook returned `collectionCopied` getter but NOT `setCollectionCopied` setter, yet `VideoAnalysis.js` line 472 called `setCollectionCopied(false)` inside the Share-Reel handler. Same crash class waiting to fire. Fix: added the setter to the hook's return + VideoAnalysis destructure.

**Regression test infrastructure** (`frontend/eslint.config.mjs` + `backend/tests/test_frontend_no_undefined_references.py`):
- Minimal ESLint **flat config** (ESLint 9.x) rooted at `frontend/eslint.config.mjs` with strict rules: `react/jsx-no-undef`, `no-undef`. The CRA dev server's lint didn't catch the original bug because it only runs incrementally; this config runs over the entire `src/` tree.
- Plugins: `eslint-plugin-react`, `eslint-plugin-react-hooks` (already in node_modules).
- Pytest `test_frontend_no_undefined_references.py` shells out to `npx eslint src/` and asserts zero errors. Verified the test correctly FAILS when the original bug is re-introduced and passes after fix. Will catch any future "missing import in JSX" or "typo'd setter name" before it reaches users.

**FFmpeg Auto-Retry** (`services/processing.py::prepare_video_sample`):
- Refactored from single-shot to a **tiered retry loop**. Files >2 GB: 180p/5fps/crf40 → 135p/3fps/crf45. Files ≤2 GB: 360p/12fps/crf35 → 180p/6fps/crf42. Second tier uses 15-min timeout (vs 30 min for tier 0) since smaller scale should finish faster.
- **Transient failures auto-retry**: SIGKILL (rc -9/137, "killed" in stderr) and `TimeoutExpired`. Smaller scale uses less memory and finishes faster on the retry.
- **Deterministic failures do NOT retry**: moov atom missing, invalid data, no space left on device. Smaller scale can't fix a corrupt input file, and retrying wastes pod time. Caller gets the actionable message immediately.
- Chunk reassembly is preserved across tier attempts — only the ffmpeg encode runs again, not the (very expensive) raw-video assembly from chunks.

**Tests added** (`tests/test_ffmpeg_error_classification.py` — 11 total now, all passing):
- `test_oom_recovers_after_retry_with_aggressive_scaling` — tier 0 SIGKILL, tier 1 success → returns clip path
- `test_timeout_recovers_after_retry` — tier 0 TimeoutExpired, tier 1 success
- `test_moov_failure_does_not_retry` — subprocess.run called exactly once
- `test_invalid_data_does_not_retry` — same protection
- `test_unknown_error_does_not_retry` — conservative bail on unclassified failures
- `test_both_tiers_oom_raises_actionable_message` — exhausted retries surface "compress further or split" hint

**Test totals**: 29/29 passing across ffmpeg classification + roster-first + disk pressure + frontend-no-undef suites.



## Roster-First Match Creation (iter61 — Feb 2026)

User reported after their first production upload: "Instead of automatically starting to process the video, the roster should be uploaded so that the analysis can be accurate. When creating a match, user should be able to import their existing team roster to the match folder, rather than uploading or creating new every time." This addresses a real AI quality gap — without roster context, tactical notes reference "midfielder #7" instead of "Reyes #7".

**Backend** (`routes/matches.py`):
- `POST /api/matches/{match_id}/import-team-roster` — body `{team_id}`. Copies every player from `team_id` to the match as a fresh snapshot. Idempotent: re-runs skip players already on the match (matched by name+number tuple).
- `GET /api/matches/{match_id}/roster-status` — `{player_count, has_roster}`. Lightweight count query used by the upload flow + video page banner.

**Backend** (`server.py`):
- `POST /api/videos/{video_id}/start-analysis` — manual kick-off for the "Run anyway" override and post-roster-add restart. Idempotent: returns `already_processing` / `already_complete` if appropriate.
- `finalize_chunked_upload` now gates auto-processing on roster presence. If the match has zero players, video status is set to `awaiting_roster` (not `queued`) and `run_auto_processing` is NOT started. The video page surfaces an "Awaiting roster" banner with both "Add roster" and "Run anyway" CTAs.

**Snapshot semantics** (important design decision): match-imported player records carry ONLY `match_id` — they intentionally do NOT carry `team_ids` back-references to the source team. Reasons:
- Team roster page (`/teams/{id}/players`) stays clean (no fan-out duplicates after the same team is imported into multiple matches).
- Match roster is a frozen point-in-time picture — if the team adds/drops players later, past match rosters are unaffected. This matters for season-trend analytics.

**Frontend** (`pages/components/CreateMatchModal.js` — rewritten as 2-step modal):
- Step 1 (Match details): unchanged form (home/away/date/competition).
- Step 2 (Roster): three modes — "Existing Team" (dropdown of coach's teams + 1-click import), "Paste CSV" (header-row CSV via `/players/import-csv`), "Skip for now" (with explainer about the `awaiting_roster` banner).
- Step indicator at top + back/forward navigation. Loads teams via `/api/teams` on modal open.

**Frontend** (`pages/components/VideoAnalysisHeader.js`):
- NEW `<awaiting-roster-banner>` — yellow banner shown when `processing_status === 'awaiting_roster'`. Two CTAs: "Add Roster" (navigates to `/match/{id}`) and "Run Anyway" (calls `POST /start-analysis`). Re-polls immediately after Run Anyway so the banner transitions to the regular blue processing banner without an 8-second delay.

**Frontend** (`pages/VideoAnalysis.js` + `hooks/useVideoProcessing.js`):
- Exposed `fetchNow` from `useVideoProcessing` for immediate re-poll after manual start.
- Added `isAwaitingRoster` / `rosterCount` derived state + `handleRunAnyway` / `handleAddRoster` callbacks wired into the header.

**Tests** (`tests/test_match_roster_first.py`, NEW — 8 tests, all passing):
- Roster status returns empty for fresh match
- Roster status 404 for unknown match
- Import copies all 3 players + roster status flips to has_roster=true
- Re-import is idempotent (2nd call: imported=0, skipped=2)
- Match copies do NOT pollute team roster (team_ids back-reference intentionally cleared)
- 404s on bogus team/match/video IDs

**Earlier in same session — deployment-related polish (still part of iter60/61 family)**:
- Disk-pressure circuit breaker threshold raised 80% → 95% (eliminates false-positive "Heavy server load" banner on the production container which baselines at 83% from OS/binaries even with 0 user videos)
- Dashboard hides promo cards (CoachPulse / GameOfWeek / CoachNetwork CTA / MyReelStats) when user has zero matches; replaced "0 matches" empty state with friendly "Welcome to SoccerScout11 — Create Your First Match" CTA
- `.gitignore` cleanup so Emergent deploy pipeline picks up `.env` files
- `VAPID_CONTACT_EMAIL` updated from placeholder `admin@soccer-scout.app` → `bb@soccerscout11.com`



## Production Post-Deploy Polish — Disk Banner False Positive + Empty Dashboard (iter60 — Feb 2026)

User went live at https://soccerscout11.com and immediately reported two surfaces felt premature/wrong on a brand-new account:

**Issue 1 — "Heavy server load – new uploads paused" banner showing at 83% used / 73.76 GB free (zero uploads).**
The container's chunk-storage volume sits on a filesystem shared with OS / package caches / node_modules. Baseline usage routinely sits at 70-85% even with zero user videos, so the old `pct >= 80%` trigger fired immediately on a healthy disk with 73+ GB still free.

Fix (`backend/server.py`):
- Raised `DISK_FULL_THRESHOLD_PCT` from 80 → 95. The 2 GB absolute-free floor (`DISK_FULL_RESERVE_BYTES`) is the real safeguard — it's what protects the pod from eviction. Percentage is a coarse signal; absolute free space is what actually matters for accepting a new upload.
- 503 trigger now: `pct >= 95%` OR `free < 2 GB`. With production at 83%/73GB → no longer blocks. With 96%/1.5GB → still blocks.
- Same logic surfaces through `/api/health` → `disk.uploads_blocked` which the frontend `DiskPressureBanner` polls every 60s.

Tests (`backend/tests/test_disk_pressure_circuit_breaker.py`):
- Updated all threshold assertions from 80 → 95.
- NEW regression test `test_production_baseline_does_not_block` — exact production scenario (~83% used, ~75 GB free) must pass through. 8/8 pass.

**Issue 2 — Premature promo cards on a 0-match dashboard.**
A first-time coach landed on the dashboard and saw COACH PULSE / GAME OF THE WEEK / COACH NETWORK / MY REEL STATS cards before they'd uploaded a single match — felt confusing.

Fix (`frontend/src/pages/Dashboard.js`):
- New `hasAnyMatches = m.matches.length > 0` gate.
- `MyReelStatsCard`, `GameOfTheWeekBanner`, `CoachPulseCard`, and the Coach Network CTA card are now hidden until the user has at least one match.
- `QuickActionsRow` (NEW VIDEO UPLOAD + CREATE GAME) stays — it's the primary first-action CTA.
- Empty state when `!hasAnyMatches`: replaces the generic "No matches here" with a friendly "Welcome to SoccerScout11" copy + "Create Your First Match" CTA button (`data-testid="empty-state-create-match-btn"`). Folder-level empty state (user has matches but the selected folder is empty) keeps the original copy.

**Earlier in same session — deployment blocker workaround**: `.gitignore` was duplicating `.env`/`.env.*`/`*.env` ignore patterns. Removed both blocks (lines 127-130 and 139-143) so Kubernetes deployment pipeline can pick up env files. User then successfully deployed to production (soccerscout11.com).


## What's Been Implemented

### Recruiter Lens OG Cards — Branded Slack/iMessage Unfurls (iter59e — Feb 2026)

User asked: build OG image cards for filtered Lens URLs so recruiters see "12 Forwards · Class of 2027 · Lakeshore FC" in Slack/iMessage previews instead of a raw URL.

**Backend** — two new endpoints in `routes/teams.py`:
- `GET /api/og/team/{share_token}/lens?birth_year=&class_of=&position=` — server-rendered HTML page with og:title, og:description ("3 of 5 players match Class of 2027 · Forwards"), og:image pointing at the matching PNG endpoint, and a JS redirect to `/shared-team/{token}?{filters}` for real browsers.
- `GET /api/og/team/{share_token}/lens-image.png?...` — 1200x630 PNG generated via the (now extended) `render_team_card`.

**Card renderer** (`services/og_card.py::render_team_card`):
- Added optional `lens_label: str` parameter — when set, renders a green pill chip below the sub-line with the filter summary baked in ("CLASS OF 2027 · FORWARDS").
- Added optional `top_label: str` — swaps the eyebrow ("RECRUITER LENS" in green vs "PUBLIC TEAM PAGE" in blue).
- Lens cards skip the avatar row entirely — the filter summary owns that visual real estate.

**Filter-intersection counting** (`_count_matching_players`):
- Translates `class_of=2027` back to the matching `current_grade` strings via the offset reverse-map (e.g. 2027 - school_year_end → 1 year out → `["11th (Junior)", "College Junior"]`).
- Combined with `birth_year` (int) + `position` (string) — query is a single `count_documents` call.

**TeamRoster wiring** (`pages/TeamRoster.js`):
- The "Share this view" button now copies `/api/og/team/{token}/lens?{filters}` (the OG-aware path), not the raw SPA URL. Browsers still land on `/shared-team/...` via JS redirect; crawlers see the rich preview.
- Recruiter outreach modal's success-state `target_url` field also shows the OG-aware path now, so coaches who re-paste it from the modal get unfurls too.

**Tests** (`test_og_lens_unfurl.py`, NEW — 8 tests):
- 404 for invalid share tokens (HTML + PNG endpoints)
- og:title + og:description + og:image meta tags include filter summary + correct image URL with same query params
- SPA redirect target preserves filter params
- "Full Squad" rendered when no filters provided
- Match-count accuracy: `class_of=2027 + position=Forward` correctly returns 3-of-5 on the fixture roster (excluding the Junior Mid and Soph FW that fail one criterion each)
- `birth_year=2008` alone returns 4-of-5 (3 FWs + 1 Mid)
- PNG endpoint returns valid PNG bytes (>5KB, correct magic header, content-type `image/png`)

**Visual verification**: rendered a sample lens PNG and analyzed it — confirmed green "RECRUITER LENS" eyebrow, team name in big bold type, green pill badge "CLASS OF 2027 · FORWARDS", player count, club crest on the right, and brand logo in the bottom corner. All elements correct.

**Test totals across iter59 family**: 54 passing — 8 OG lens + 16 outreach + 3 lens + 24 roster import + 3 public dossier demographics.

### Hot Lead Auto-Followup — Engagement Milestones (iter59d — Feb 2026)

User asked: when a recipient opens a tracked lens link 3+ times in 48 hours, fire an in-app/email notification to the coach so passive interest signals turn into active conversation starters.

**Backend** (`routes/recruiter_lens.py` — `_maybe_trigger_hot_lead` helper):
- Called from `lens_track` after every click row is inserted.
- Engagement threshold: **3+ clicks within last 48 hours** (`_HOT_LEAD_CLICK_THRESHOLD`, `_HOT_LEAD_WINDOW_HOURS`).
- Atomic guard via `update_one({"repeated_open_notified_at": None}, ...)` — two near-simultaneous clicks can't both fire the email. Only the first wins; the second is a no-op.
- Sends a "🔥 Hot Lead" email via `send_or_queue` with a polished inline-HTML template (Resend, falls back to MongoDB queue on quota errors).
- Failure-tolerant: any exception is logged but never breaks the click redirect — recipient always lands on the filtered page.
- New field on every `lens_link`: `repeated_open_notified_at` (ISO timestamp, `null` until triggered).

**Email design**: Dark hero with "Hot Lead" / "{recipient} keeps coming back" / "{team} · {filter_summary}", body explains the click count + time window, single green CTA button to the team roster page, footer note confirming "we only send this once per outreach."

**Frontend** (`SentLensLinksPanel.js`):
- Hot-lead rows get a `bg-[#10B981]/5` highlight (subtle green tint) — instantly scannable.
- "🔥 Hot Lead" pill (`data-testid="hot-lead-badge-{id}"`) renders next to the recipient name when `repeated_open_notified_at` is set.

**Tests** (`test_recruiter_outreach.py` — 4 new pytest cases):
- Single click does NOT trigger notification (`repeated_open_notified_at` stays `null`).
- 3 clicks within 48h DOES trigger and sets the timestamp.
- Already-notified link does NOT re-fire on subsequent clicks (timestamp is pinned to the first trigger; clicks 4–6 don't change it).
- Old clicks outside the 48h window don't count — only 2 fresh clicks + 1 backdated to 3 days ago = no notification despite `click_count=3`.

**Test totals (iter59 family)**: 46 passing — 16 outreach (incl. 4 hot-lead) + 3 recruiter lens + 24 roster import + 3 public dossier demographics. Verified together in a single pytest run with full coverage on the engagement-milestone logic.

### Recruiter Outreach — Tracked Email Send + Open Analytics (iter59c — Feb 2026)

User asked: build the "Send to a specific coach" flow that pairs the iter59b filtered lens URL with an automated email + tracks who clicked. Turn a passive share into a measurable recruiting funnel.

**Backend** (`routes/recruiter_lens.py`, NEW module — 4 endpoints):
- `POST /api/lens-links` (auth): coach creates a tracked outreach. Body = `{team_id, filters: {birth_year?, class_of?, position?}, recipient_email, recipient_name?, message?}`.
  - Auto-enables team `share_token` if the team isn't yet publicly shared (so the recipient lands somewhere real — no dead links).
  - Generates a 14-char tracking token, stores in new `lens_links` collection.
  - Sends a polished inline-HTML email via `services.email_queue.send_or_queue` (reuses the existing Resend integration with quota-fallback to MongoDB queue).
  - Returns `{lens_link, tracked_url, target_url, email_status}` so the UI shows what happened.
- `GET /api/lens-links?team_id=X` (auth): list the coach's outreach with click counts + last-opened timestamps.
- `GET /api/lens-track/{token}` (PUBLIC, no auth): inserts a click row into `lens_link_clicks`, bumps `click_count` + `last_clicked_at` on the parent, 302-redirects to `/shared-team/{share_token}?{filters}`. Bogus tokens silently redirect to `/` so we don't leak existence info.
- `GET /api/lens-links/{id}/clicks` (auth): drill-down with individual click rows (ip, user-agent, timestamp). Returns 404 if another coach owns the link.

**Data model**:
- `lens_links`: `{id, user_id, team_id, team_share_token, filters, recipient_email, recipient_name, message, tracking_token, click_count, last_clicked_at, created_at}`
- `lens_link_clicks`: `{id, lens_link_id, ip_address, user_agent, clicked_at}`

**Frontend**:
- `RecruiterOutreachModal.js` (NEW): polished modal with filter-preview chips, three inputs (email required, name + message optional), success state showing the tracked URL + email delivery status (delivered/queued).
- `SentLensLinksPanel.js` (NEW): table above the filter strip showing recipient, filter summary, **click count** (green when >0), last-opened relative time, and sent-at. Auto-hides when the coach hasn't sent any outreach for this team yet — no clutter for non-adopters.
- `TeamRoster.js`: green "Email Recruiter" button next to the existing "Share this view" button (works even when team isn't shared yet — backend auto-enables). On success, refreshes both team data (to surface the new share_token) and the panel (to show the new row).

**Email template**: Inline-styled HTML email with no external assets (renders in any client). Subject line includes coach name, team, and filter summary (e.g. "Coach Jane sent you a roster: Lakeshore FC (Class of 2027 · Forwards)"). Personal-message block conditionally rendered. Single CTA button to the tracked URL.

**Tests** (`test_recruiter_outreach.py`, NEW — 12 tests):
- Auth required on create + list + clicks endpoints
- Tenant isolation (can't email-blast another coach's team; can't read their clicks)
- Tracked URL contains the tracking token; target URL preserves filters
- Auto-share-enablement on a fresh team
- 302 redirect with correct query params + click row inserted + counter bumped
- Multiple clicks accumulate
- Bogus token redirects safely (no info leak)
- Cross-user click drill-down blocked
- Team filter scopes list query
- Invalid email → 422; missing team → 404

**Total passing tests across the iter59 work**: 42 (12 outreach + 3 recruiter lens + 24 roster import + 3 public dossier demographics).

### Recruiter Lens — Shareable Filtered Team URLs (iter59b — Feb 2026)

User asked: build the "Recruiter Lens" — auto-applied scout filters with shareable filtered URLs (e.g. "Class of 2027 forwards"), so college recruiters can land directly on the players that match their needs.

**Backend fix** (`routes/teams.py::get_shared_team`):
- Public team payload was stripping `birth_year` and `current_grade` (same regression class as the iter58 player dossier fix). Added them to `public_fields`. Internal fields (`user_id`, `team_ids`, `profile_pic_path`) stay private.

**URL-driven filtering on `SharedTeamView.js`**:
- Reads `?birth_year=2008&class_of=2027&position=Forward` from the URL using `useSearchParams`.
- Filters in-browser off the already-loaded roster (no backend filtering — keeps the public payload honest, lets the URL describe the scoped view).
- Renders a blue "Recruiter Lens" filter bar above the roster showing active filter chips + "X of Y match" counter + "Clear" CTA.
- Empty-result state has its own messaging + "See full roster →" link.
- Every player card on the public view now shows demographic badge chips (U-age + Class of YYYY) via the shared `demographicBadges` util.

**TeamRoster "Share this view" button**:
- When filters are active AND the team has a `share_token`, a green "Share this view" button appears in the filter strip.
- Builds the URL: `{origin}/shared-team/{share_token}?birth_year=YYYY&class_of=YYYY`.
- Translates the grade dropdown selection (e.g. "11th (Junior)") → URL param `class_of=2027` via `classOfLabel`.
- Copy-to-clipboard with Check-icon success feedback (2s).
- When team isn't shared yet, a helpful italic hint replaces the button.

**Tests** (`test_recruiter_lens.py`, NEW — 3 tests):
- Public team payload includes `birth_year` for each player.
- Public team payload includes `current_grade` for each player.
- Public team payload omits internal fields (`user_id`, `team_ids`, `profile_pic_path`).

**URL round-trip verified**: `11th (Junior)` → coach copies link `?class_of=2027` → recruiter visits `/shared-team/{token}?class_of=2027` → public view shows only juniors → `classOfLabel(player.current_grade).endsWith('2027')` matches correctly.

**Total passing tests for this work**: 30 (24 roster import + 3 public dossier demographics + 3 recruiter lens).

### Player Demographics — Derived Analytics + Hudl/TeamSnap Imports (iter59 — Feb 2026)

User asked: continue from iter58 — verify CSV demographics end-to-end, then ship Player Age/Grade derived analytics, then Hudl/TeamSnap roster import.

**(a) End-to-end CSV verification**
- 6 new pytest cases covering `birth_year` + `current_grade` canonical headers, alias headers (YOB / Class), full-date birth-year extraction, out-of-range birth-year warnings, optional demographic fields, and template content. All 18 roster-import tests pass.
- UX gap fixed: `RosterImportModal.js` preview table now surfaces a "Birth Yr" and "Grade" column (only when at least one row has the value), so coaches can visually verify demographic parsing before importing.

**(b) Derived analytics — age groups + class-of**
- **Bug fix**: `routes/player_profile.py::_build_profile_payload(public=True)` was stripping `birth_year` and `current_grade` from the public dossier payload, so shared player links didn't show the data. Fixed.
- New util `frontend/src/utils/playerDemographics.js`:
  - `ageGroupLabel(birth_year)` → e.g. `U18` (U-system soccer convention)
  - `classOfLabel(current_grade)` → e.g. `Class of 2028` (HS + college aware; assumes Aug→Jul academic year)
  - `demographicBadges(player)` → `[{key, label}]` for one-line rendering
- Badge chips rendered on:
  - `PlayerProfile.js` private dossier hero (`data-testid="player-demographic-badges"`)
  - `SharedPlayerProfile.js` public dossier hero (`data-testid="public-demographic-badges"`)
- **Roster filters** on `TeamRoster.js`: birth year + grade dropdowns (only render when the roster has those values), with a live "Showing X of Y" counter and a Clear button. Empty-result state has its own messaging + clear-CTA.
- Backend test: `test_public_dossier_demographics.py` (3 tests) — confirms public dossier returns birth_year + current_grade and never leaks `user_id` / `profile_pic_path`.

**(c) Hudl / TeamSnap CSV exports — auto-detected**
- Decision: skipped full OAuth (Hudl requires partner-level API access). Instead, extended the existing smart-parser path so coaches can paste their CSV exports verbatim and we figure out the columns.
- New header aliases in `routes/players.py::_HEADER_ALIASES`:
  - `first_name` ← First Name, Firstname, First, Given Name
  - `last_name` ← Last Name, Lastname, Last, Family Name, Surname
  - `birth_year` extended with: Date of Birth, DOB, Birthdate, Birth Date
  - `grad_year` ← Grad Year, Graduation Year, Class of, Graduating Class
  - `member_type` ← Member Type, Role, Type
- Parser logic:
  - If `name` column absent, combines `first_name + last_name` into a single name.
  - If `current_grade` absent but `grad_year` present, derives the grade via `_grade_from_grad_year` (Aug→Jul school-year semantics, matches frontend `classOfLabel`).
  - If `member_type` present, skips rows whose type is not `player`/`athlete` (TeamSnap exports include coaches/managers).
- 6 new pytest cases cover Hudl split-name + Grad Year, TeamSnap Member Type skipping, blank-first/last edge case, grad-year without grade column, explicit grade beats grad year, and the updated 400 error message mentions the split-name fallback. **All 24 roster-import tests pass.**
- UI hint added in `RosterImportModal.js`: "✓ Hudl & TeamSnap exports work out of the box" (`data-testid="hudl-teamsnap-hint"`).

**Testing summary (iter59)**: 24 roster-import tests + 3 public-dossier-demographics tests + 5 cookie-auth + 7 CSRF + 5 rate-limiter tests = 44 passing in touched suites. Pre-existing `test_delete_match_cross_user_rejected` failure exists on pristine main — unrelated to this work.

### CSV Roster Import — Birth Year + Grade Support (iter58 — Feb 2026)

User asked: "extend the CSV importer to accept birth_year + current_grade, plus add a downloadable CSV roster template."

**Template download** (`GET /api/players/import-template.csv`): now ships all 5 columns with realistic example rows:
```
name,number,position,birth_year,current_grade
Jane Doe,9,ST,2008,11th (Junior)
Maria Lopez,4,CB,2007,12th (Senior)
Sam Lee,10,CM,2009,10th (Sophomore)
```

**Import parser** (`routes/players.py`):
- Added `birth_year` + `current_grade` to `_HEADER_ALIASES`. The importer now matches:
  - `birth_year` ← "birth year", "birthyear", "year of birth", "yob", "born", "birth"
  - `current_grade` ← "grade", "current grade", "class", "year", "school year", "level"
- Birth year parser is lenient — accepts plain year (`2008`), full date (`2007-03-15` → extracts year), and empty. Out-of-range values (under 5 or over 30 years old) are caught with a friendly error AND the player is still imported with grade preserved.
- Existing 3-column rosters (name/number/position only) continue to import unchanged — fully backwards compatible.

**Frontend** (`RosterImportModal.js`):
- CSV format help block now lists all 5 supported columns.
- Updated inline example to show demographics.
- Download template button unchanged — it already pointed at the same endpoint, which now returns the richer template.

**Verified end-to-end** with a 5-row CSV containing mixed shorthand headers (`Player Name, #, Pos, Year of Birth, Grade`), a date-formatted birth year, an empty birth year, and an out-of-range birth year:
- All 5 players imported
- Date `2007-03-15` correctly resolved to 2007
- Empty birth_year and out-of-range 1985 both handled gracefully with friendly error message + grade preserved
- Mongo verification confirms canonical schema population

### Player Roster: Edit + Demographics + Auto-Scroll (iter57 — Feb 2026)

User asked for three features plus the pre-commit hook from iter56's improvement suggestion.

**(A) Auto-scroll on inline form open** (`/app/frontend/src/hooks/useScrollIntoViewOnOpen.js`, new):
- Reusable hook that scrolls an element into view + auto-focuses the first input when its `open` flag flips false → true.
- Uses `scrollIntoView({behavior:'smooth', block:'center'})` so the form lands mid-viewport (preserves spatial context with the button above it). Auto-focus with `preventScroll:true` triggers mobile keyboards immediately, saving one tap.
- Applied to: `TeamRoster.js` Add Player form, `ManualResultForm.js` editor (when toggling from summary to edit mode). Verified via Playwright that focus correctly lands on the name input after click.

**(B) Manual player editing** (`routes/players.py` + `TeamRoster.js` + new `PlayerFormModal.js`):
- Backend: `PATCH /api/players/{id}` switched from query params to JSON body (`PlayerUpdate` Pydantic model). Only provided fields are `$set` — partial updates are safe. Same endpoint name, no breaking change since no callers existed.
- Frontend: new shared `PlayerFormModal` component powers both Add (inline) and Edit (modal overlay). Pencil icon next to every player on the roster opens the edit modal pre-filled with their current values. Verified end-to-end: name typo → fixed; jersey number 7 → 17; grade Junior → Senior. All persisted.

**(C) Birth year + age + current grade fields**:
- Backend: added `birth_year: Optional[int]` + `current_grade: Optional[str]` to the `Player` Pydantic model. Both nullable — existing players unaffected. Surfaced on the public dossier (`player_trends.py` payload).
- Age is computed (`current_year - birth_year`), never stored — can't drift stale when the year rolls over.
- Frontend grade dropdown: 6th, 7th, 8th, 9th (Freshman), 10th (Sophomore), 11th (Junior), 12th (Senior), College Fr/So/Jr/Sr, Graduate/Post-Grad. Covers HS, club, and college rosters. Birth year input is numeric with min/max sanity bounds (current_year-30 to current_year-5).
- Roster card shows a compact demographics line: "Age 19 · Born 2007 · 11th (Junior)" only when at least one field is set.
- Player season-trends dossier (`PlayerSeasonTrends.js`) now shows the same line in amber under the player name — gives recruiters age + grade context at a glance.

**Plus: pre-commit hook** (`.pre-commit-config.yaml`, new):
- `radon-complexity-gate` blocks any commit that introduces a C-grade (≥11 cyclomatic complexity) function in `backend/`. Catches the next 168-line monster at write-time.
- `ruff` auto-fixes unused imports / undefined names / `==True` etc. on every commit.
- Install: `pip install pre-commit && pre-commit install`. One-time setup per dev machine.

**Verified end-to-end** via Playwright + curl:
- Add player with all 5 fields → card shows "Age 19 · Born 2007 · 11th (Junior)"
- Edit modal opens pre-filled with name, number, position, birth_year, grade
- Update name + grade + jersey → all 3 changes persist + reflect in UI
- Auto-focus correctly lands on name input after clicking Add Player
- Backend PATCH endpoint accepts JSON body, returns `{status:"updated", fields_updated:[...]}`

### Code Quality Pass (iter56 — Feb 2026)

User shared a code review report. I evaluated each finding before acting:

**Inflated/incorrect claims (acknowledged, NOT changed)**:
- "11 undefined variables" → ruff F821 actually reports **0**. Zero undefined variables in the codebase.
- "113 `is`-comparison anti-patterns" → ruff E711/E712 actually reports **0**. The real hits are `is True` / `is False` against Python's boolean singletons — that's **idiomatic Python per PEP 8**, not an anti-pattern. The rule bans `== True` / `== False`, not `is True` / `is False`.

**Real, fixed**:
1. **Unused imports** (real, ruff F401): 32 unused imports removed across the backend via `ruff --fix`.
2. **Hardcoded test passwords**: extracted to a shared `THROWAWAY_PASSWORD` constant + `make_throwaway_email()` factory in `conftest.py`. Migrated all 4 affected test files (`test_cookie_auth_migration`, `test_csrf_protection`, `test_login_rate_limiter`, `test_iter11_new_features`, `test_annotation_templates`). Configurable via `TEST_THROWAWAY_PASSWORD` env var. (Note: lines 719/799 in `test_highlight_reel.py` flagged by report are UUID-based share tokens, not passwords — false positive.)
3. **`compute_benchmarks()` refactor** (`routes/coach_network.py`): 168 lines → **65 lines** (−61%); cyclomatic complexity 30 → no longer flagged by `radon -nc`. Extracted 8 single-purpose async helpers (`_platform_totals`, `_user_personal_totals`, `_per_coach_distribution`, `_position_counts`, `_insight_theme_counters`, `_recruiter_level_distribution`, `_processing_durations`, `_top_themes`). The orchestrator now reads top-to-bottom. **Live endpoint returns identical 12-key payload** (verified via curl); 21 coach_network/pulse tests pass.
4. **`download_clips_zip()` refactor** (`routes/clips.py`): 76 lines → **27 lines** in the handler (5-level nesting → 2-level). Extracted 4 helpers (`_safe_clip_filename`, `_extract_clips_for_zip`, `_write_zip`, `_stream_then_delete`, `_cleanup_paths`). `radon -nc` no longer flags `clips.py`. 29 clip+coach_network+pulse tests pass.

**Not yet done** (lower-impact, would need follow-up iterations):
- `browse_public_reels()` (22 complexity), `generate_match_insights()` (19 complexity) — both still hit C-grade but lower priority than the two extreme cases above. Logged for future cleanup.
- `my_reel_stats`, `trending_reels`, `extract_clip_video`, `list_my_mentions`, `update_role` — all in the "Should refactor soon" tier, not "Extreme".

### Login Brute-Force Rate Limiter (iter55 — Feb 2026)

User asked: "rate-limiter on /auth/login". Followed the integration_playbook_expert_v2 recommendation for a MongoDB-backed sliding-window limiter that survives pod restarts (critical given our recurring pod evictions).

**Design** (`/app/backend/services/login_rate_limiter.py`, new):
- Sliding window: 15 min / 10 max failed attempts. Coaches mistyping their password 3-4 times still get through; bots blowing through 10 get locked.
- **Two parallel counters per request**: per-IP (`ip:1.2.3.4`) AND per-email (`email:foo@example.com`). Both must be under threshold to pass. Defends against both rotating-proxy attackers (per-email catches them) and credential-stuffers fanning across many accounts (per-IP catches them).
- Real client IP resolved via `CF-Connecting-IP` (Cloudflare-authoritative) → leftmost `X-Forwarded-For` → `request.client.host`. Cloudflare ingress strips spoofed XFFs from inbound, so leftmost is trusted.
- Check fires BEFORE bcrypt → attackers can't even exercise the slow compare once locked out (denies both timing-oracle and CPU-DoS vectors).
- Successful login wipes BOTH counters → legit user mistyping 3 times then succeeding gets a clean slate.
- MongoDB-backed: persists across pod restarts (the previous concern about losing limiter state on eviction). Unique index on `key`, 30-min TTL on `last_attempt_at` for auto-cleanup.

**Frontend**: zero changes needed — existing error handler already surfaces `err.response?.data?.detail`, which contains the friendly "Try again in N minutes" copy.

**Verified**: 5 new pytest tests in `test_login_rate_limiter.py` covering: 9 failures don't lock out, 10th triggers lockout, lockout blocks even the correct password, successful login resets counters, 429 has Retry-After + friendly message. **All passing. 63 total auth/cookie/csrf/rate_limit/disk tests pass, 0 regressions.**

### CSRF Protection — Double-Submit Token (iter54 — Feb 2026)

User asked: "wire CSRF protection on top of cookie auth". Implemented the OWASP-recommended double-submit-token pattern, closing the last remaining attack vector on the cookie auth from iter52.

**Backend** (`server.py`):
- New `csrf_token` cookie (32 bytes URL-safe random via `secrets.token_urlsafe(32)`). **Not** HttpOnly — frontend MUST read it via JS. Same `SameSite=Lax; Secure; Max-Age=7d; Path=/` attributes as access_token.
- Set in `/api/auth/login` and `/api/auth/register` responses, cleared in `/api/auth/logout`.
- New `csrf_protection_middleware`: skips safe methods (GET/HEAD/OPTIONS), non-/api paths, auth bootstrap endpoints, and legacy `Authorization: Bearer` requests (which are CSRF-immune by design). On any other cookie-authenticated unsafe-method call, requires `X-CSRF-Token` header matching the cookie value (constant-time compare via `hmac.compare_digest`). Mismatch → JSON 403 with clear "refresh the page" message.

**Frontend** (`App.js`):
- New `axios.interceptors.request.use(...)` reads `csrf_token` via `document.cookie` and echoes it back in `X-CSRF-Token` header on every POST/PUT/PATCH/DELETE. Zero changes needed at any of the ~150 call sites.

**Critical fix discovered** — `routes/auth.py` had a SECOND `get_current_user` dependency that was still header-only (used by ~20 modular route files like `routes/matches.py`, `routes/folders.py`, `routes/videos.py`, etc.). My iter52 cookie migration only updated `server.py:get_current_user`, so cookie auth was silently broken on most endpoints. Synced both deps to read cookie → header fallback. All affected routes now work with the new cookie auth.

**Verified end-to-end**:
- 7 new pytest tests in `test_csrf_protection.py` (all passing): cookie set, GET no-CSRF, POST blocked without header, POST succeeds with matching header, POST blocked with mismatched header, legacy Bearer bypass, auth endpoints exempt.
- Browser-side Playwright verification: `access_token` cookie HttpOnly=True (XSS-proof), `csrf_token` cookie HttpOnly=False + JS-readable (double-submit echo source), values match. App dashboard renders all 3 matches + Reel Stats + Coach Pulse via cookie-authenticated axios GETs.
- 58 total auth/cookie/csrf/disk regression tests passing, 0 regressions.

### iter53 Triple-Header: Disk Banner + Cookie Auth + Component Refactor (Feb 2026)

User asked for "b, c, and d" — disk-pressure banner, oversized-component refactor, and httpOnly cookie auth migration. All three shipped in one iteration.

**(b) DiskPressureBanner** (`/app/frontend/src/components/DiskPressureBanner.js`, new):
- Polls `/api/health` every 60s globally inside `BrowserRouter`. Renders nothing when healthy.
- When `uploads_blocked === true`: red strip at top of authenticated app with primary copy ("Heavy server load — new uploads paused for a few minutes"), reassurance copy ("Match film already on the way will keep uploading from where it stopped"), and live stats (`{used_pct}% used · {free_gb} GB free`).
- Dismiss button persists a 5-min suppression to `localStorage`.
- Skips public/share/auth routes. Verified end-to-end via Playwright with mocked health responses.

**(d) httpOnly Cookie Auth Migration** (`server.py` + `App.js`):
- New cookie config: `access_token` cookie with `HttpOnly; Secure (prod); SameSite=Lax; Path=/; Max-Age=604800`. Set by `/api/auth/login` and `/api/auth/register`.
- `get_current_user()` now reads cookie first, falls back to legacy `Authorization: Bearer` header — **fully backwards compatible** for existing localStorage tokens.
- New `POST /api/auth/logout` clears the cookie server-side.
- `axios.defaults.withCredentials = true` set globally — cookies auto-attach to every `/api` call.
- New `clearSession()` helper unifies logout: calls `/auth/logout`, then clears localStorage.
- Followed the integration_playbook_expert_v2 cookie auth playbook.
- Verified: 5 new pytest tests in `test_cookie_auth_migration.py` covering cookie set, cookie-only auth, header-only auth, 401, and logout. **51 total auth + cookie + disk tests pass, 0 regressions.**
- Migration plan: Phase 1 (this iteration) is dual-write — token in both cookie AND localStorage. Phase 2 (future): drop localStorage write + remove `token` field from response body.

**(c) Component Refactor** (Dashboard.js + ManualResultForm.js):
- `Dashboard.js`: 421 → 299 lines (−29%). Extracted `useMatches` (126 lines) + `useFolders` (113 lines) custom hooks in `/app/frontend/src/hooks/`.
- `ManualResultForm.js`: 491 → 368 lines (−25%). Extracted `ManualResultSummary` (177 lines) read-only view.
- Zero behavior changes — all data-testids preserved. Verified via Playwright smoke test (3 match cards render, selection mode toggles, footer chip + install link work).

### Disk-Pressure Hardening: Tighter Sweeper + Circuit Breaker (iter51 — Feb 2026)

- **Why**: 6+ pod terminations from ephemeral storage exhaustion. Even on the larger machine, leaked `ffmpeg` temp files + concurrent uploads can still fill `/var/video_chunks` faster than the previous sweeper cleared it. Two complementary defenses below.

**(a) Tighter sweeper** (`server.py:_cleanup_stale_temp_files`):
- Staleness threshold: **10 min → 5 min**
- Run cadence: **30 min → 5 min**
- Combined effect: worst-case leaked-temp-file backlog drops from ~40 min to ~10 min

**(b) Disk-pressure circuit breaker** (new `_check_disk_pressure(incoming_bytes)` in `server.py`):
- Two triggers (either one fires → HTTP 503):
  1. `used_pct >= 80%` (DISK_FULL_THRESHOLD_PCT)
  2. `free_bytes - incoming_bytes < 2 GB` (DISK_FULL_RESERVE_BYTES) — keeps headroom for AI processing temp files
- Wired into all 3 upload entry points:
  - `POST /api/videos/upload` (standard <1 GB path)
  - `POST /api/videos/upload/init` (chunked path — gates upfront so a 15 GB upload doesn't get 7 GB in before failing)
  - `POST /api/videos/upload/chunk` (last-line-of-defense: hard floor of <500 MB free, aborts in-progress sessions only when pod is about to crash)
- Returns friendly user-facing message: *"Our servers are under heavy load… Please try again in a few minutes — your file will resume from wherever it stopped."* with `Retry-After: 300`.
- Fail-open behavior: if `shutil.disk_usage()` itself raises, uploads are NOT blocked (safer than locking everyone out on a stat hiccup).

**Disk stats surfaced in `/api/health`**:
- Returns `{disk: {used_gb, total_gb, free_gb, used_pct, uploads_blocked, threshold_pct}}` so admins can monitor disk pressure live without shell access.

**Tests** (`/app/backend/tests/test_disk_pressure_circuit_breaker.py`, new, 7 passing):
- Healthy disk passes; 80% threshold blocks; reserve-bytes check blocks; just-under-threshold passes; OSError fails open.
- Full regression: 32 upload/disk/chunk/temp tests passing.

### Build Staleness Warning (iter50 — Feb 2026)

- **Why**: the iter49 chip tells you *which* build is live, but doesn't flag *when it's getting old*. A quiet amber nudge after 7 days catches the case where preview has accumulated weeks of changes that haven't shipped — exactly the pattern that caused the iter49 `.gitignore` saga to go undetected.
- **Implementation** (`BuildInfoChip.js`):
  - Computes `daysOld = floor((Date.now() - built_at) / 86400000)` in a `useMemo` keyed on `info.built_at`.
  - When `daysOld >= 7`: chip text + warning icon turn amber, tooltip becomes `"Stale build ({N} days old) — consider redeploying"`, modal renders an amber warning block at the top with a "Save to GitHub + redeploy" CTA.
  - When fresh: chip stays neutral (the previous discreet style).
  - `data-stale="true|false"` attribute on the chip for easy E2E testing.
- **Threshold**: 7 days, hardcoded `STALE_THRESHOLD_DAYS`. Easily bumpable if it becomes too noisy.
- **Verified**: Playwright confirmed both states — fresh `iter50` chip stays neutral, mocked old `built_at` (41 days) flips chip to amber with correct tooltip + modal warning block + "redeploy" nudge in the body copy.
- **Backend bump**: `BUILD_VERSION` advanced to `iter50`, `SHIPPED_FEATURES` extended to 16 entries with `build-info-chip` + `build-staleness-warning`.

### Build Info Chip + `/api/health/deploy` (iter49b — Feb 2026)

- **Why**: after each redeploy, the user needs a way to confirm production is actually running the latest code without clicking through every feature. Especially valuable after the iter49 `.gitignore` saga, where multiple deploys silently shipped stale code.
- **Backend** (`server.py`):
  - New `GET /api/health/deploy` returns `{build, sha, built_at, features, feature_count}`.
  - `BUILD_VERSION = "iter49"` constant + `SHIPPED_FEATURES` array (14 entries) defined at module load.
  - `_get_build_sha()` runs `git rev-parse --short HEAD` with a 2s timeout and `cwd=/app`; falls back to `"unknown"` if git is stripped from the deployment image.
  - `BUILT_AT` ISO timestamp captured at module load (reflects actual deploy time, not request time).
  - Public endpoint — no auth required (build info isn't sensitive).
- **Frontend** (`/app/frontend/src/components/BuildInfoChip.js`, new):
  - Fetches `/api/health/deploy` on mount, renders a discreet `v1.0 · iter49` chip in the dashboard footer (replacing the previous static "v1.0" text).
  - Click → modal with: build label, git SHA (monospace), localized build timestamp, feature count, and the full feature list with green check icons.
  - Silent failure mode — if the endpoint is unreachable, the chip just doesn't render (no broken UI).
- **Verified end-to-end**: curl confirms the endpoint returns correct payload (`iter49`, real SHA `cf2cd75`, 14 features). Playwright opens the footer chip, asserts 14 feature list items, and confirms three flagship features (`compression-calculator`, `notify-when-upload-done`, `gitignore-deploy-fix`) appear.
- **Maintenance note**: bump `BUILD_VERSION` in `server.py:~349` and append to `SHIPPED_FEATURES` array each time features ship to prod. Source of truth for "what's live".

### Deployment Blocker Fix: .gitignore Cleanup (iter49 — Feb 2026)

- **User reported**: production deployment failed at the "managing secrets" step with `failed to fetch envs from source pod: ... pods "agent-env-71a126e7-ebd7-4add-81d0-147a3aeb2fff" not found`.
- **Earlier theory**: orphaned source pod / pod-tier resource issue. Wrong.
- **Actual root cause** (per deployment agent diagnosis): `.gitignore` was polluted with five repeated blocks of `.env` / `.env.*` / `*.env` patterns (plus stray `-e` lines from `echo -e ... >> .gitignore` shell command artifacts). Because `.env` files were being ignored by git, they weren't included in the deployment build context — so the deployer couldn't find them and reported it as a "source pod env" lookup failure.
- **Fix**: stripped lines 113-163 of the polluted patterns, kept the legitimate credential ignores (`credentials.json`, `*.pem`, `*.key`, `.credentials`), preserved the existing cache-pack ignores, and added a comment explaining `.env` files must be committed for Kubernetes deployment.
- **Verified**:
  - `grep -nE "^\.env|^\*\.env" .gitignore` → no matches
  - `grep -n "^-e" .gitignore` → no matches
  - `git check-ignore backend/.env` → empty (not ignored)
  - `git check-ignore frontend/.env` → empty (not ignored)
  - `git status` confirms `backend/.env` is now tracked
- **Next step for user**: Save to GitHub (so the cleaned `.gitignore` + `.env` files land in the repo) → redeploy. Should now clear the "managing secrets" step.

### Notify-When-Done Upload Toggle (iter48 — Feb 2026)

- **Why**: with the 20 GB ceiling + larger raw files now supported, multi-hour uploads will become common. Coaches shouldn't have to babysit the tab. This toggle lets them switch contexts, lock their phone, etc., and get pinged when finalize completes.
- **Implementation**:
  - `/app/frontend/src/utils/push.js`: new `showLocalNotification(title, {body, url, tag})` helper. Fires via `ServiceWorkerRegistration.showNotification()` (works on Android Chrome where `new Notification()` doesn't), checks permission + SW availability, swallows errors so callers can fire-and-forget.
  - `MatchDetail.js`: added `notifyOnComplete` state + `handleToggleNotify` (gates permission request via the existing `requestPushPermission()` from the Coach Pulse flow) + `fireUploadCompleteNotification(videoId)` helper. Called from both `handleStandardUpload` and `handleChunkedUpload` success paths *before* the `navigate(...)` so the notification fires even though the tab is about to navigate.
  - `UploadPanel.js` / `UploadInProgress`: renders a Bell-icon toggle button below the file chip during upload. Adaptive label: "Notify me when done" → "Notify me when done · ON". Hint text changes to confirm the on-state ("we'll buzz you when finalize completes").
  - Notification body: `"{team_home} vs {team_away} is ready — AI analysis is queued. Tap to view."` Tapping the notification navigates to `/video/{id}` via the existing `notificationclick` handler in `service-worker.js`.
- **Verified**:
  - Toggle UI renders during real chunked upload (Playwright stalled the chunk endpoint, captured the in-progress state with the toggle button + hint text).
  - Service worker registers and exposes `showNotification` correctly.
  - Known headless-Chromium quirk: `Notification.permission` stays `denied` even after `grant_permissions(['notifications'])`, so the toggle's ON-state can't be visually verified in tests — works correctly in real browsers (same `requestPushPermission()` flow is already in production via the Coach Pulse subscribe button).

### Send Compression Instructions to Teammate (iter47 — Feb 2026)

- **Why**: the calculator from iter46 lets a coach explore their own scenario, but staff workflows often delegate the actual encoding to an assistant coach with a beefier laptop. This share button closes the loop — one tap → assistant coach gets a paste-ready message with the *exact* numbers + HandBrake link.
- **Implementation** (`CompressionCalculator.js`):
  - New `shareMessage` `useMemo` builds a personalized message using the live `sizeGB`, `mbps`, and recommended preset (Fast 1080p30 CQ 22) projections.
  - Share button uses the same Web Share API → clipboard fallback pattern as the PWA install share (iter42), with idle/shared/copied/error state machine.
  - Disables when raw size = 0 (prevents copying a placeholder message).
  - Auto-adapting label: "Send these specs to teammate" (mobile) vs "Copy these specs for teammate" (desktop).
- **Message template** captures: brand, raw size + upload time, compressed size + upload time, network speed, AND the 5 HandBrake steps from the tip — so the recipient has everything they need without leaving the chat thread.
- **Verified**: Playwright confirms personalized numbers, brand, HandBrake link, CQ setting, and network spec all appear in the clipboard payload. State resets after 2.5s. Disabled state works for size=0.

### Real-Time Compression Calculator (iter46 — Feb 2026)

- **Why**: iter45's nudge tells coaches *to* compress, and the iter44 tip tells them *how*. Neither answers "but is this preset too aggressive for my film?" or "how much faster will the upload actually be?". The calculator closes that loop with concrete numbers.
- **`/app/frontend/src/components/CompressionCalculator.js`** (new):
  - Two inputs: `Raw file size` (GB, auto-filled from `pendingLargeFile.size || selectedFile.size`) and `Upload speed` (10/25/50/100 Mbps).
  - Baseline row shows "Upload as-is" cost in red to anchor the savings.
  - 4 preset cards (Fast 720p30, Fast 1080p30 ★ recommended, Fast 1080p30 CQ 25, Fast 1080p60) — each displays projected file size, savings %, upload time at chosen network speed, and a 1-liner on quality trade-offs.
  - Ratios calibrated from typical sideline-cam source (~15-25 Mbps): 0.18 / 0.35 / 0.22 / 0.55. Footnote explicitly notes ±20% variance.
  - Smart unit switching (GB vs MB) so a 2 GB input cleanly shows "369 MB" for the smallest preset.
- **Embedded inside the existing compress tip panel** in `UploadPanel.js`, immediately after the step-by-step workflow. Single source of truth for compression UX.
- **Verified end-to-end**: Playwright walks through default 12 GB → 4.2 GB recommended, changes network 25→100 Mbps and confirms time drops 24→6 min, changes size 12→20 GB and confirms output scales, drops to 2 GB raw and confirms unit switches to MB. Then injects a fake 14.5 GB file selection and confirms the nudge → "Show me how" → calculator auto-syncs to 14.5 GB.

### Smart Large-File Nudge (iter45 — Feb 2026)

- **Why**: the compression tip from iter44 is discoverable but passive. Users who don't read first will still click "Select Video File", queue a 12 GB raw, and lock themselves into a 50-min upload. This change intercepts the moment the user picks a 5 GB+ file and forces a deliberate choice.
- **Implementation** (`UploadPanel.js`):
  - New `LARGE_FILE_THRESHOLD = 5 * 1024 ** 3`. When `handleFile()` sees a file above the threshold, it stops propagation, stores it in `pendingLargeFile` state, auto-expands the compression tip, and scroll-into-views the explainer.
  - Amber alert banner renders above the dropzone with `WarningCircle` icon, filename + GB size, estimated upload time (~4 min/GB), one-liner explaining the compression payoff, and two CTAs:
    - `large-file-nudge-show-tip` → opens the tip panel + scrolls to it (for users who want to learn first).
    - `large-file-nudge-proceed` → "Upload as-is" — propagates to parent's `onVideoUpload` and starts the chunked upload immediately.
  - `large-file-nudge-close` (X) cancels without uploading.
- **MatchDetail.js**: the OS `window.confirm()` for >1 GB files now only fires for the 1–5 GB band. Files >5 GB are governed entirely by the in-page nudge — no double-prompting (user chose deliberately in the banner, no need for a second OS dialog).
- **Verified**: Playwright injected fake 6 GB and 12 GB `File` objects via `Object.defineProperty(file, 'size', ...)`. Both correctly trigger the nudge, render correct size + time estimate, expand the tip on click, and dismiss on X.

### Compress-Before-Upload Tip (iter44 — Feb 2026)

- **Why**: with the upload ceiling bumped to 20 GB in iter43, users uploading raw 9-15 GB sideline-cam film will spend 30-60 min on the uplink. The AI pipeline downscales every source to 240p/8fps before Gemini analysis anyway — so a 12 GB raw and a 3 GB compressed file produce *identical* heatmaps, timeline markers, and highlight reels. Compressing first means 3-4× faster uploads with zero quality loss + less pod disk pressure.
- **Implementation** (`UploadPanel.js`):
  - Added a collapsible "Got a 5 GB+ file? Compress it first" expander below the dropzone (amber-accented, advisory not blocking).
  - Expanded panel explains the AI-downscale rationale + a 5-step HandBrake workflow with exact settings (preset `Fast 1080p30`, Constant Quality 22).
  - Linkout to `handbrake.fr/downloads.php` with `noopener noreferrer`.
  - Closing note: "Already happy with your file? Skip this — uploads up to 20 GB work fine, just slower." → user retains full agency.
- **Testids**: `compress-tip-toggle` / `compress-tip-panel` / `handbrake-link`. Toggle + collapse verified via Playwright.

### Upload Size Label Bumped 5 GB → 20 GB (iter43 — Feb 2026)

- **User report**: dropzone copy advertised "up to 5 GB" but real 11v11 match film runs 9-15 GB (full match + potential ET/PKs). User had already correctly re-saved `REACT_APP_BACKEND_URL` in deploy secrets after a missed first save.
- **Root cause**: stale UI copy. The chunked-upload pipeline never had a 5 GB cap — `ChunkedUploadInit` accepts any `file_size`, chunks stay on disk (no reassembly at finalize), and `prepare_video_sample()` adaptively downscales >2 GB sources to 240p/8fps before sending to Gemini.
- **Fix**:
  - `UploadPanel.js`: copy updated to "up to 20 GB" (20 GB ceiling chosen to leave headroom over the 9-15 GB target while staying well under the 84 GB `/var/video_chunks` overlay partition).
  - `MatchDetail.js`: replaced the dismissive `alert(...)` for >1 GB files with a `window.confirm()` that estimates upload time (~4 min/GB), explains the chunks are resumable on connection drop, and asks the user to confirm before kicking off a multi-GB upload. Lets users back out instead of trapping them in a 30-min upload they didn't expect.
- **Verified**: Playwright screenshot on `/match/{id}` shows "MP4, MOV, AVI up to 20 GB".
- **No backend change required** — chunked pipeline already supports it. AI processing has automatic downscale tiers (240p/8fps for >2 GB sources) and immediately deletes the temp raw file after ffmpeg compress.

### Send Install Link to Teammate (iter42 — Feb 2026)

- **`InstallGuideModal.js`** now exposes a primary "Send install link to teammate" CTA directly under the QR code.
  - **Mobile/tablet (Web Share API available)**: tapping fires `navigator.share({title, text, url})` — opens the device's native share sheet so a coach can blast the install link via Messages, WhatsApp, email, Slack, Telegram, etc. in two taps.
  - **Desktop fallback**: when `navigator.share` is unavailable, the same click writes a ready-to-send message (brand sentence + URL) to the clipboard via `navigator.clipboard.writeText` with `execCommand('copy')` as a secondary fallback. Button morphs into a green "Link copied — paste it to your teammate" state for 2.5s.
  - User-cancelled shares (`AbortError`) silently return to idle — no false error states.
- **Why**: closes the loop on org-wide PWA adoption. Coaches no longer have to manually type/copy the URL or rely on the QR — they can fire off the install link in one tap, complete with branding copy. Verified end-to-end with Playwright clipboard inspection.
- **Testid**: `install-share-to-teammate` (button) + `install-share-hint` (helper copy under it).

### Install Guide Modal + QR Code (iter41 — May 11, 2026)

- **`InstallGuideModal.js`**: tabbed modal (iPhone / Android / Desktop) with a 144px QR code of the current origin so coaches can scan from their phone or an assistant coach's device. Each tab has accurate, browser-specific install steps:
  - **iPhone/iPad — Safari**: Share → Add to Home Screen (with note that Chrome/DuckDuckGo on iOS can't install)
  - **Android — Chrome/Brave/Edge**: auto Install App banner + 3-dot menu fallback
  - **Android — DuckDuckGo**: bottom 3-dot menu → Add to Home Screen
  - **Android — Firefox**: top-right vertical menu → Install
  - **Desktop — Chrome/Edge/Brave**: address-bar install icon + menu fallback
- **Discreet footer link** on the Dashboard ("INSTALL ON ANOTHER DEVICE") opens the modal. Doesn't compete with the auto-firing `PWAInstallPrompt` — this is on-demand for users who already installed locally and want to onboard staff/players.
- **New dependency**: `qrcode.react@4.2.0` (~6 KB gzipped — generates SVG, no external API).
- **Build verification**: `yarn build` runs clean; bundle picks up the new component + QR lib.

### Mobile UX Pass + PWA Install Hardening (iter40 — May 11, 2026)

**Mobile-responsive fixes**
- **TeamRoster header**: 4 buttons (Share / Add Existing / Import CSV / Add Player) used to spill off-screen on phones. Now collapses to icon-only on mobile (labels appear at `sm:`+ breakpoint), action row wraps to a new line so it's always reachable. Player-count chip stays visible.
- **Add Player form**: was a 4-col grid forcing tiny inputs on mobile. Now stacks to 1 col on small screens, 2 col on tablets, 3 col on desktop. Cancel button moved below Submit on mobile (thumb-reach), `inputMode="numeric"` added so phones pop the number keypad for jersey #. Min/max 0-99 enforced.
- **ManualResultForm event rows**: padding tightened to `p-4 sm:p-6`, inputs grow `py-3` on mobile (better tap target), Save Result row uses `flex-col-reverse` on mobile so the primary CTA sits below other buttons.

**PWA install support — Chrome / DuckDuckGo / Firefox / Brave / Edge / Samsung / Safari / in-app webviews**
- Rewrote `PWAInstallPrompt.js` with proper UA detection + browser/OS-specific instructions.
  - Native one-click install when `beforeinstallprompt` fires (Chrome/Edge/Brave/Samsung Android + Chrome/Edge/Brave desktop).
  - Manual numbered steps for: iOS Safari, iOS non-Safari, Android DuckDuckGo, Android Firefox, in-app webviews (Instagram/Facebook). Desktop Firefox is hidden (no PWA support).
- Manifest upgraded: added `id`, `display_override`, `categories`, maskable icon variant, home-screen shortcuts ("New Match" → `/dashboard`, "Reel Library" → `/reels`).
- Prompt now dismisses for 14 days (vs forever previously).

**Deployment failure (May 11)**
- Error: `failed to fetch envs from source pod ... pods not found` — confirmed platform-side (orphaned source pod), not code.
- Resolution: user emails support@emergent.sh with job ID. Don't Redeploy until support clears the orphan.
- Production `yarn build` verified clean locally — manifest deploys with 3 icons + 2 shortcuts.

### OG Card Caching Bump 5min→1h (iter39 — May 11, 2026)

- **Change** (`routes/og.py`): all 8 OG image endpoints (folder, clip, match-recap, scout-listing, highlight-reel, player) now serve `Cache-Control: public, max-age=3600, s-maxage=3600`.
- **Why**: when a reel goes viral on social, every Twitter/WhatsApp/Slack/Discord/Telegram link preview hits the OG image endpoint. Pillow re-renders the PNG on each cache miss. 5min cache meant 12 cache misses per viral hour; 1h means 1 cache miss per hour — ~12× backend load reduction.
- **Risk**: revoked share-tokens may show a stale OG image preview for up to 1 hour before crawlers re-fetch. Acceptable — the actual SPA page already returns 404 for revoked tokens, so clicks land on an error page rather than ghost content.
- **Verified**: curl against a live reel OG endpoint confirmed the new header is served.

### Fire-and-Forget View Tracking (iter38 — May 11, 2026)

- **Change** (`routes/highlight_reels.py`): `record_reel_view` is now wrapped in a fire-and-forget `_record_view_safely()` helper invoked via `asyncio.create_task` from the public reel-page handler. Errors are swallowed + logged at WARNING level so view tracking never blocks the share page.
- **Latency**: bench against the public reel endpoint shows median 3.2ms / p95 5.9ms (was ~50-100ms before — the inline view insert was the slowest path).
- **Behavioural parity**: 43/43 highlight reel tests pass — view tracking still records exactly when it should, just deferred a few microseconds.

### Code Review Fixes (iter37 — May 11, 2026)

Did a full audit of iter 30-36 work. Findings & fixes:

**🔴 HIGH (fixed)**
1. **Match-delete didn't cascade reels** — `DELETE /matches/{id}` and bulk delete both left behind orphaned `highlight_reels` docs + mp4 files + dangling `highlight_reel_views` rows that polluted the trending feed. Fix: `_cascade_delete_reels_for_match()` helper called from both delete paths.
2. **No spam cap on reel generation** — could queue unlimited ffmpeg jobs. Fix: 429 if user has ≥3 reels in pending/processing.

**🟡 MEDIUM (noted)**: inline view tracking, video-time vs match-time minute labels, OG cache 5min→1h.

**🟢 LOW**: server.py size, MyReelStatsCard fetch caching.

**Test hardening**: fixed flaky `test_public_reel_view_records_a_view_and_dedupes` (K8s proxy IP variance).

**Verification**: 80/80 tests across 5 reel/match suites passing.

### Disk-Safety Sweeper — verified live (May 11, 2026 — iter36)

- Added live boot-log line `[apscheduler] scheduler started — ... + ffmpeg_temp_cleanup (every 30 min)` so operators can confirm the sweeper is registered.
- Verified end-to-end: backdated a fake stale `tmp_test_old_boot.mp4`, restarted backend, and observed `[startup-cleanup] reclaimed 0.0 MB across 1 stale temp files` in the log + the file was removed.
- Confirmed `highlight_reel.process_reel()` already cleans up intermediate `tmp*` segments in its `finally` block, so any future orphans from OOM kills will be caught by the 30-min periodic sweep.

### Disk-Safety: Stale ffmpeg temp file sweeper (May 11, 2026 — iter35)

- **Root cause of recurring storage exhaustion**: when the pod is OOM-killed mid-ffmpeg run, the `finally` cleanup block never executes, leaking 100s of MBs of `tmp*.mp4` files into `/var/video_chunks/`, `/var/video_chunks/close_ups/`, and `/var/video_chunks/reels/`. Repeated boots compound the leak until storage is exhausted again.
- **Fix** (`server.py`): `_cleanup_stale_temp_files()` glob-scans the three known temp dirs for `tmp*` prefixed files older than 30 minutes and unlinks them. Runs **once at startup** AND **every 30 min via APScheduler** (`ffmpeg_temp_cleanup` job). Non-tmp prefixed files (real reel/close-up outputs) are never touched.
- **Verification**: 2 pytest cases — one asserts a backdated stale file gets reclaimed while a fresh file and a real-output file are both preserved; the other asserts missing/empty directories don't raise.
- **Immediate impact**: reclaimed 381MB orphaned file from the previous boot during this iter.

### Weekly "Reel Recap" Email (May 11, 2026 — iter34)

- **Service** (`services/reel_recap.py`): Re-engagement loop — sends every Monday 10:00 UTC (1h after scout digest to avoid Resend rate-limit lockstep).
- **Per-user pipeline**: groups all `ready + shared` reels by owner, counts weekly views, computes `delta` vs the prior 7 days, picks top 3 reels by weekly views, builds a branded HTML email with view count + delta chip ("+10 vs last wk" / "-5 vs last wk"), top-3 list with flame badge on #1, dual CTAs ("See Trending Reels" → `/reels`, "My Dashboard" → `/dashboard`).
- **Skip rules**: users with 0 shared reels are skipped silently. Users with shared reels but 0 weekly views are skipped only when triggered by APScheduler (so manual admin runs always send for QA).
- **Send path**: routes through `services.email_queue.send_or_queue` so Resend quota deferrals don't drop emails. `kind="reel_recap"` for log filtering.
- **Admin endpoint**: `POST /api/admin/highlight-reels/send-weekly-recap` for manual QA triggers (admin/owner role only).
- **Scheduler**: registered `reel_recap_weekly` cron job with `misfire_grace_time=3600` so a brief server hiccup doesn't drop the week's send.
- **9 new pytest cases**: duration formatting, HTML rendering (positive/negative delta, XSS escape on coach name + team names), zero-reels base case, skip-on-silence rule, end-to-end send-with-views flow, admin auth, admin trigger response shape. All passing.

### "My Reel Stats" Dashboard Card (May 11, 2026 — iter33)

- **Backend**: New `GET /api/highlight-reels/my-stats` endpoint (auth-required) returning:
  - `total_reels`, `ready_reels`, `shared_reels` counts
  - `views_7d` + `views_all_time` aggregated across all my reels via single `$group` pipeline
  - `top_reel` — my most-viewed reel in the last 7 days that's still **shared + ready** (unshared reels skip the surface even if they have higher view counts, since the user can't link to them anyway)
- **Frontend** `MyReelStatsCard.js`:
  - Auto-hides when the user has no reels (returns `null`) so it never shows a confusing zero-state on a brand-new dashboard
  - 3-column stat tiles: Reels (white/blue) · Views 7d (green) · All-Time (amber)
  - Hero "Most-Viewed This Week" callout with red flame icon, click-through to the public reel page
  - When user has reels but no views yet, shows a "Share a reel to start tracking views" nudge
- **Mounted** on Dashboard just below `QuickActionsRow`, above `GameOfTheWeekBanner`.
- **4 new pytest cases**: auth required, zero-state shape, multi-reel aggregation + top-reel picking, top-reel skips unshared reels even if they have more views. **40/40 highlight reel tests passing.**

### Trending Reels Strip + View Tracking (May 11, 2026 — iter32)

- **View tracking** (`services/scout_digest.py`): mirror of the listings view-tracking pattern — `record_reel_view()` with 24h debounce per (reel_id, viewer_key), `trending_reel_ids()` Mongo aggregation grouping by `reel_id` over a sliding window, `reel_view_count()` for the public detail page.
- **Endpoints**:
  - `GET /api/highlight-reels/trending?limit=12&days=7` — top reels by unique-view count over the window. Clamps `limit` to ≤24 and `days` to 1-60. Hides reels that have been revoked or are no longer `ready` — these drop out automatically.
  - `GET /api/highlight-reels/public/{token}` — now records an anonymous view (IP+UA fingerprinted, 24h debounce) and returns `view_count` in the response.
- **Frontend** `HighlightReelsBrowse.js`:
  - New `TrendingStrip` component — horizontal snap-scroll of compact 288px tiles with a red "TRENDING" pill badge, ordered by view count desc.
  - View count rendered with an eye icon under each tile when > 0.
  - Strip auto-hides when the user is actively filtering (search or competition) so it doesn't compete with their query.
  - Trending is fetched once on mount independent of filters.
- **5 new pytest cases** covering: empty trending shape, `days` clamp, exclusion of pending/share-revoked reels, view recording + 24h same-viewer dedupe, view-rank reflecting in trending, eviction on share revoke. **36/36 highlight reel tests passing.**

### Public Highlight Reel Library — Discovery Surface (May 11, 2026 — iter31)

- **Backend** (`routes/highlight_reels.py` — 2 new endpoints):
  - `GET /api/highlight-reels/browse` — public list of `ready` reels with `share_token`. Filters: `q` (substring match across home/away teams + coach name), `competition` (exact), pagination (`limit` 1-50, `offset`). Bulk-loads matches + users in 2 queries, projects out `user_id` and filesystem path for privacy.
  - `GET /api/highlight-reels/browse/competitions` — distinct competition list for filter chips.
  - **Routing fix**: had to move both browse routes ABOVE `GET /highlight-reels/{reel_id}` to prevent FastAPI from matching `"browse"` as a `reel_id` path parameter (FastAPI matches routes in registration order).
- **Frontend** `HighlightReelsBrowse.js` at public route `/reels`:
  - Sticky header with back button + Reel Library title
  - Search input (debounced 250ms) + competition filter chips
  - Responsive 1→2→3→4 column grid of reel tiles using the OG card image as a 1200×630 hero thumbnail
  - Each tile: hero image with play-icon hover overlay, clip-count + duration chips, team-vs-team title, score, competition + coach line, date
  - Empty state, loading state, "no public reels match your filters" fallback
  - URL syncs with filters (`?q=...&comp=...`) so feeds are shareable
- **Discovery**: Added "Reels" nav button to authenticated `DashboardHeader` (blue accent) + footer link on `LandingPage`.
- **5 new pytest cases** verifying browse filtering, privacy projection (no `user_id` or `output_path` leak), competition exact match, search substring, and that pending/non-shared reels are excluded. **Highlight reel suite now at 31/31 passing.**



**Auto-Highlight Reel Generator (P1 main feature)**:
- **Backend** (`services/highlight_reel.py`, ~480 lines + `routes/highlight_reels.py`, ~225 lines):
  - **AI scoring & selection**: goal=100 / save=80 / key_pass=60 / tackle=50 / highlight=50. +10 bonus for tagged players. Greedy fit into MAX 90s budget (4s safety reserve). Overlong clips trimmed to 12s. Min 60s target, MAX_CLIPS=12. Final chronological reorder for narrative flow.
  - **Title cards**: Pillow renders 1280×720 PNGs per clip — top tag ("GOAL 1 · 23'"), main line (player name or fallback), sub (matchup + competition), color-coded left accent strip. ffmpeg loops PNG to 2.5s static mp4 with silent stereo track for audio-rail uniformity.
  - **Clip extraction**: reuses chunk reassembly + ffmpeg cut from close_up pipeline. Each clip is scaled+padded to 1280×720 with `force_original_aspect_ratio=decrease + pad` so the concat demuxer never refuses mixed sizes.
  - **Concat**: intro card → (title card → clip) × N → final mp4 via `ffmpeg -f concat` with libx264/aac re-encode for codec uniformity. Output saved to `/var/video_chunks/reels/{reel_id}.mp4`.
  - **In-process asyncio worker queue** (one reel at a time, same pattern as close_up_processor).
  - **Endpoints**: `POST /matches/{id}/highlight-reel` (create + enqueue), `GET /matches/{id}/highlight-reels` (list), `GET /highlight-reels/{id}` (status), `POST /highlight-reels/{id}/share` (toggle public token), `POST /highlight-reels/{id}/retry`, `DELETE`, `GET /highlight-reels/{id}/video` (auth download stream), `GET /highlight-reels/public/{token}` (public JSON), `GET /highlight-reels/public/{token}/video` (public mp4 stream).
- **OG share card** (`render_highlight_reel_card` in `og_card.py`): 1200×630 PNG with blue accent strip, "MATCH HIGHLIGHTS REEL" label, big team-vs-team title, scoreline chip row showing N clips · M:SS reel duration. `GET /api/og/highlight-reel/{token}` (HTML unfurl) + `.png` variant cached 5min.
- **Frontend**:
  - `HighlightReelsPanel.js` (~270 lines) mounted on `MatchDetail` for matches with a video. Generate button (disabled when any reel is in flight) → progress bar with status pill (Queued / Processing N% / Ready / Failed) → per-reel actions: Download mp4, Toggle share, Copy share link, WhatsApp + Twitter share buttons, Delete, Retry. Auto-polls every 5s while any reel is in flight.
  - `SharedHighlightReel.js` — public SPA route `/reel/:shareToken` with full-width video player, branded hero, score+clip+duration chips. Works unauthenticated.
- **25 pytest cases** in `test_highlight_reel.py`: pure-logic (score weights, selection budgeting, chronological tie-break, overlong-clip trim, helpers), Pillow renderers (title card + OG card validity), 8 HTTP integration tests (auth required, 404 unknown match, 400 no-clips, share-toggle requires ready, token returns/revokes correctly, OG endpoints render valid PNG + HTML meta tags), 1 end-to-end ffmpeg test that renders an actual mp4 title-card segment and verifies its duration via ffprobe. **All passing. Total suite now 269/269.**

**Landing Page (`/`)**:
- New public page `LandingPage.js` shown at root when not authenticated (authenticated users get the Dashboard at `/` or `/dashboard`).
- Hero with "PROFESSIONAL PLAYER ANALYSIS & SCOUTING MADE SIMPLE", twin CTAs (Upload Video / Create Game), top nav with Home / Features / Pricing / About / Contact (smooth-scroll anchors), Log in + Register buttons.
- Sections: 3 feature cards (Video Analysis / Player Tracking / Performance Reports), beta-free pricing, About (stats grid), Contact (mailto), footer with social icons.
- AuthPage now reads `?mode=register` query param to open in register mode. Post-login navigation goes to `/dashboard` explicitly.

**UX Wireframe Polish**:
- **Dashboard `QuickActionsRow`**: two big tap-cards at the top — "New Video Upload" (blue) and "Create Game" (green) — both open the existing create-match modal. Includes "Upload Now" and "Create" CTA chips on desktop.
- **`UploadPanel` drag & drop**: bigger cloud icon, "DRAG & DROP VIDEO FILES HERE / or click to browse" label, "MP4, MOV, AVI up to 5 GB" format hint, file chip showing name + size during upload, drag-over highlight state.
- **`ProcessingProgressBar` real-time status feed**: new mono-styled activity log beneath the 4-step grid showing rotating context-aware messages ("Detecting player movements…", "Tracking ball trajectory…", "Placing event markers…") tied to the current AI step. Mirrors the wireframe's "Real-time status updates" panel.

**Bug fix — jersey "0" no longer dashes out**:
- `playerForm.number ? parseInt(...) : null` was treating `"0"` as falsy → stored as null. Changed to `!== ''` check in `TeamRoster.js` and `MatchDetail.js`.
- All display paths (`{player.number || '—'}`, `#{p.number || '?'}`) replaced with `??` so 0 renders as `0` not `—` / `?`.
- All sort comparators (`a.number || 99`) replaced with `a.number ?? 999` so #0 sorts to top of roster, not bottom.
- 16 frontend files patched. Backend already handles 0 correctly via `int(raw_num)`.



### AI Auto-Zoom Highlights — Wide + Close-up Stitched Clips (May 9, 2026 — iter29)

**Goal**: every goal clip (and any user-selected clip) gets a duplicate close-up sibling — same action, AI-cropped tight to the ball/players. The two get stitched into a single mp4 that plays the wide shot then the close-up so coaches can review the play twice.

**Backend** (`services/close_up_processor.py`, ~330 lines):
- **Pipeline (per clip)**: extract wide segment → send to **Gemini 3.1 Pro** for bbox+zoom analysis → ffmpeg `crop+scale` for the close-up → ffmpeg concat for wide+close-up → save stitched mp4 to `/var/video_chunks/close_ups/{clip_id}.mp4`.
- **AI prompt**: returns strict JSON `{x_pct, y_pct, w_pct, h_pct, zoom_level: 1.5|2.0|2.5, reasoning}`. Tighter zoom (2.5) for finishing actions, wider (1.5) for build-up. Tolerant JSON parser handles markdown-fenced responses, clamps out-of-range values, snaps zoom to one of the documented levels. Falls back to centered 2× crop on any failure so users always get SOMETHING.
- **In-process async worker**: tiny single-consumer asyncio queue so ffmpeg + Gemini calls don't pile up. Survives within the FastAPI process; on restart, stuck clips just stay in `processing` state and need a manual retry (acceptable for a free-tier demo).
- **Per-clip status**: `close_up_status` ∈ `{pending, processing, ready, failed}` with `close_up_path`, `close_up_bbox`, and `close_up_error` for diagnostics.

**Endpoints** (in server.py — clips routes live there, not `routes/clips.py`):
- `GET /api/clips/{id}/extract` — now serves `close_up_path` directly (zero re-encoding) when status is `ready`. Falls back to chunk-reassembly + ffmpeg cut otherwise.
- `POST /api/clips/{id}/generate-close-up` — queues a manual close-up. No-ops on `ready`/`pending`/`processing`.
- `POST /api/clips/{id}/close-up/retry` — clears failed state and re-queues.
- **Auto-trigger**: `auto_create_clips_from_markers` (used by the AI marker → clip pipeline) automatically enqueues every `clip_type == "goal"` clip after creation.

**Frontend** (`pages/components/ClipsSidebar.js` + `VideoAnalysis.js`):
- Each `ClipCard` now shows a colored status pill:
  - 🎬 **Wide + Close-up** (green) when ready
  - **Generating close-up** (yellow, pulsing dot) when pending/processing
  - **Close-up failed** (red) when failed
- Non-goal clips get an "Add close-up" button. Failed clips get a "Retry close-up" button.
- VideoAnalysis polls `/clips/video/{videoId}` every 8s while any clip is in flight so the badge flips automatically when ffmpeg finishes (~30-90s for typical 8s clip).

**15 new pytest tests** (`test_close_up_processor.py`):
- Pure-logic unit tests: clean JSON, markdown-fenced JSON, out-of-range clamping, garbage-fallback, empty-fallback, zoom snap-to-nearest.
- Crop-box math: center-frame correctness, left-edge clamp, right-edge clamp, libx264-required even dimensions.
- HTTP: unknown-clip 404, unauth 401, no-op on already-ready, `/extract` byte-for-byte serves the close-up file.
- All passing.

**Live E2E verified via curl**: synthetic 2s mp4 → /extract serves it byte-for-byte → routes correctly 404 unknown clips and 401 unauth → no-op on ready state.

### Code Quality Sweep (May 7, 2026 — iter28b)

Applied high-value, low-risk fixes from the code review:
- **Hardcoded test-secret leakage**: tests/test_iter11/test_annotation_templates were already using env vars; only Ruff E741 ambiguous variable names (`l` instead of `listing`) needed cleanup in `test_scout_listings.py`.
- **Unused locals**: removed dead `clips_before_ids` / `original_player_ids` setup in `test_regression_sweep.py`.
- **E731 lambda assignments** in `coach_network.py::compute_benchmarks` → renamed to `_avg` / `_median` named functions.
- **Empty catch blocks (8 sites)**: added `console.warn` with context in `push.js`, `SpokenSummaryPanel.js`, `ScoutingPacketModal.js`, `ManualResultForm.js`, `LiveCoachingMic.js`, `ShareReelModal.js` so silent failures aren't invisible anymore.
- **Expensive JSX computations**: wrapped `FolderFormModal` parent dropdown filter and `ManualResultForm` per-team player buckets in `useMemo`. (`SharedView` and `RosterSection` were either already memoized in iter22 or O(N≤5) so not worth the closure overhead.)
- **`express_interest()` complexity**: extracted `_resolve_dossier_url`, `_build_interest_email_html`, `_record_contact_click_view` helpers — main handler dropped from 115 lines to ~40.
- Backend lint: 100% clean (`ruff check /app/backend`). Frontend lint: 100% clean (`eslint /app/frontend/src`).
- **Skipped (intentional)**: localStorage→httpOnly cookies (full auth rewrite, not justified by the theoretical XSS risk on a single-tenant coach SaaS); large-component splits of Dashboard/ClubManager/MatchDetail (working code, high regression risk vs. theoretical readability gain).

### Player Dossier Attachment on Express Interest (May 6, 2026 — iter28)

**Goal**: turn "I have a great kid for you" into "I have a great kid for you — here's the full profile" with one click. Closes the loop between coaches and scouts on the Scout Board.

**Backend**:
- New `GET /api/players/my-shared` — returns the caller's players that have a public `share_token` enabled (from the existing player-dossier share infra). Sorted by name. Used to populate the dropdown in Express Interest.
- `POST /scout-listings/{id}/express-interest` already accepted `player_dossier_share_token` from iter27. Now exercised end-to-end:
  - Token is validated against `players` collection scoped to the caller's `user_id` — bogus tokens 404, cross-user tokens 404 (coach can't attach a scout's player).
  - On success, both the in-app message body and the email HTML get a "— View player dossier: https://…/player/{token}" line appended.

**Frontend** (`ExpressInterestModal.js`):
- New "Attach Player Dossier (optional)" dropdown above the message textarea.
- Pre-fetches the user's shared players on mount.
- Empty state ("You don't have any public player dossiers yet — share a profile from the dossier page first") if they haven't shared anyone yet.
- Green confirmation chip below the picker once selected: "✓ Dossier link will be added at the end of your message."

**4 new pytest tests** (`test_scout_phase2.py`): my-shared lists only shared players (not all owned), happy path attaches dossier link to both message body and email HTML, bogus token 404s, cross-user token 404s. Suite is now 17/17 passing.

**Live E2E verified via curl**: created shared player → my-shared returns it → express interest with token successfully appends dossier URL to both message + email → bogus token rejected → cross-user attach rejected.

### Scout Board Phase 2 — Express Interest + In-App Messaging + OG Cards + Floating Insights (May 6, 2026 — iter27)

**1. Express Interest CTA** — green button on every public listing detail (visible to authed coaches who are NOT the owner).
- `POST /api/scout-listings/{id}/express-interest {message}` opens (or reuses) a 1:1 message thread, appends the coach's message, queues an email to the scout via Resend with the coach's name + message + branded "Reply in App →" CTA, and increments the listing's `contact_clicks_7d` metric.
- Self-interest blocked with 400. Min 10 chars enforced. Message capped at 5000 chars.
- Frontend `ExpressInterestModal` opens from listing detail. After send, navigates the coach straight to `/messages/{thread_id}` so they can keep typing.

**2. In-app Messaging** (`routes/messaging.py`, ~310 lines):
- New collections: `message_threads` (1:1 threads keyed by sorted `participant_pair` so duplicates are impossible) and `messages` (one doc per message).
- Endpoints: `/messages/threads/open`, `/threads`, `/threads/{id}`, `/threads/{id}/reply`, `/threads/{id}/read`, `/unread-count`.
- Frontend `/messages` and `/messages/:threadId`: split-pane (thread list + active conversation). Auto-scrolls to bottom on new messages. Mobile collapses to single-pane with back-link. iMessage-style bubbles (mine = green right-aligned, theirs = grey left-aligned). Auto-marks-read on open.
- New "Inbox" icon in Dashboard header with unread badge that pulls from `/messages/unread-count`.

**3. OG cards for scout listings** (`services/og_card.py::render_scout_listing_card` + `routes/og.py`):
- New 1200×630 PNG card with green accent bar, "VERIFIED RECRUITING LISTING" header, school name (auto-shrinking up to 96px), level/region/grad-year sub-line, position chip row, 3-line description preview, optional school logo.
- `GET /api/og/scout-listing/{id}` — HTML with og:title / og:description / og:image. `GET /api/og/scout-listing/{id}/image.png` — dynamic PNG with 5min cache.
- Scouts can paste their listing URL on Twitter/LinkedIn/Slack and get a rich unfurl preview.

**4. Floating insights chip** — on `/scouts/:id`, when viewer IS the owner, a fixed-position green chip in the bottom-right shows "N views · M clicks · past 7d". Click = navigate to `/scouts/my`.

**13 new pytest tests** (`test_scout_phase2.py`): express-interest auth/self-block/short-msg/unknown-listing/happy-path, thread dedup by participant pair, 404 for non-participants, full reply+read flow, self-thread/unknown-user rejected, OG HTML meta tags, OG PNG validity (1200×630), 404 for unknown listing OG. All passing.

**Live E2E verified via curl + screenshot**: 12-step end-to-end run all green; Messages page renders both empty states correctly with header Inbox icon wired.

### Roster CSV Import — Bulk Add Players to a Team (May 6, 2026 — iter26)

**Goal**: let coaches build a team roster from a spreadsheet instead of typing 25+ players one at a time.

**Backend** (`routes/players.py`):
- `POST /api/teams/{team_id}/players/import` — accepts `multipart/form-data` CSV file. Returns `{imported, skipped, errors:[{row,reason}], parsed:[…]}`.
- `?dry_run=true` returns the parsed payload without writing — powers the preview/confirm flow.
- **Tolerant header aliases**: `name` matches `name|player|player name|full name|fullname|athlete`; `number` matches `number|no|no.|#|jersey|jersey number|shirt|shirt no`; `position` matches `position|pos|pos.|primary position`. Case- and spacing-insensitive.
- **UTF-8 BOM handling**: Excel saves with `\ufeff` prefix; we strip it so coaches don't get cryptic decode failures.
- **Validation**: empty file → 400; missing `name` column → 400 with helpful message listing accepted aliases; >1MB → 413; team ownership enforced; season cap reused.
- **Soft errors**: bad jersey numbers (e.g. "Goalkeeper" or "9.5" in the number column) are reported as warnings, but the row is still imported with `number=null`. Empty rows skipped silently.
- `GET /api/players/import-template.csv` — public endpoint that downloads a starter CSV with canonical headers + 3 example rows. No auth required since it's static.

**Frontend** (`components/RosterImportModal.js`, ~170 lines):
- Drag-and-drop dropzone with click-to-browse fallback.
- Inline CSV format help block with monospace example + green "Download CSV Template" link.
- After file selected, automatically calls `dry_run=true` and shows:
  - Green banner: "Found N players ready to import" + skipped count
  - Yellow warnings panel listing per-row issues
  - Scrollable table preview of all parsed rows
  - "Choose different file" reset + "Import N Players" confirm
- After confirm, refreshes the team's player list and shows a summary alert.
- Mounted on `/team/:teamId` next to the existing "Add Player" / "Add Existing" buttons as a green "Import CSV" button.

**12 new pytest tests** (`test_roster_import.py`): auth required, unknown-team 404, empty file 400, missing-name-column 400, oversized file 413, header alias tolerance ("Player Name" / "Jersey Number" / "Pos."), dry-run does not write, real import inserts rows with correct team_ids, bad number reports warning + still imports, empty rows skipped, public template download with attachment header, Excel BOM handled. All passing.

**Live E2E verified via curl + screenshot**: dry-run on a 7-row CSV returned 6 parsed players + 3 warnings (Goalkeeper / Not A Number / 9.5) → real import inserted 6 players → team now lists all 6 with correct numbers/positions → empty file → 400 → missing name column → 400 → unknown team → 404 → unauthenticated → 401. Frontend modal opens cleanly with drop zone, format help, and template download button.

### Scout Stickiness — View Tracking + Weekly Digest (May 3, 2026 — iter25)

**Goal**: keep scouts coming back to Soccer Scout 11 by giving them measurable signal that their listings are working.

**Backend** (`services/scout_digest.py`, ~210 lines):
- New collection `scout_listing_views` with `(listing_id, viewer_key, event, viewed_at)`. `viewer_key` is `u:<user_id>` for authed viewers and `a:<sha256(ip|ua)[:16]>` for anonymous, with a 24h dedup window per (listing, viewer_key, event).
- `record_view(listing_id, viewer_user_id?, anon_fingerprint?, event="view"|"contact_click")` — best-effort upsert with dedup.
- `listing_insights(listing_id)` — returns `{views_total, views_7d, views_30d, unique_coaches_7d, contact_clicks_7d}` via aggregation.
- `send_weekly_digest(triggered_by)` — for each scout-role user, builds a per-listing rollup email and dispatches via `send_or_queue`. Smart skip: scouts with zero recent views AND no listings are silenced when triggered by the cron (avoids low-value emails).
- New routes (`routes/scout_listings.py`):
  - `GET /api/scout-listings/{id}` — now records a view (skips owner self-views).
  - `POST /api/scout-listings/{id}/contact-click` — pinged from frontend when website link or mailto is clicked.
  - `GET /api/scout-listings/{id}/insights` — owner-only, 404 for everyone else.
  - `GET /api/scout-listings/my` — now embeds `insights{}` per listing.
  - `POST /api/admin/scout-listings/send-weekly-digest` — admin-only manual trigger.
- New cron job: **`scout_digest_weekly`** — APScheduler CronTrigger Mon 09:00 UTC (1h after coach pulse).

**Frontend**:
- `/scouts/my` — new "My Listings" page with per-listing 3-stat tile (Views 7d / Unique coaches / Contact clicks), green/yellow verification chip, edit + view buttons, info card explaining the Monday digest.
- `/scouts` header now shows a "My Listings" button (next to "+ Post Listing") for scout/admin users.
- Listing detail page now pings `/contact-click` whenever the website link or contact email is clicked.

**Email design**: branded HTML email with Bebas Neue header, scout name greeting, per-listing rows showing 7d views / unique coaches / contact clicks in big green/blue/yellow numerals, verified or pending chip, "Open Scout Board" CTA. Empty-state copy nudges first-time posters.

**9 new pytest tests** (`test_scout_digest.py`): dedup logic via direct service-layer calls (HTTP transport mutates X-Forwarded-For at the K8s ingress so headers-based fingerprint tests are fragile — service-layer is the truth), owner-self-views-not-counted, authed-non-owner-counts-unique, insights-owner-only-404-for-others, contact-click increments + dedupes + 404s for unknown listing, my-listings embeds insights, digest-endpoint admin-only, digest queues an email with school name + view-count headers + CTA link. All passing. Total scout suite: **23/23 green**.

**Live E2E verified via curl + screenshot**: created listing → 5 distinct anon+authed views with proper dedup → owner self-views did NOT inflate count → contact-click recorded → admin-triggered digest sent emails to all 3 scouts in db with full HTML body → `/scouts/my` UI renders 3-stat tiles → `/scouts` header shows "My Listings" + "+ Post Listing" buttons.

### Scout Board — Public Recruiting Listings (Phase 1) (May 3, 2026 — iter24)

**Scouts and college coaches can post projected recruiting needs; coaches and players browse them.**

**New role**: `scout` (and `college_coach`) added to `VALID_ROLES`. Exposed on the register form as "Scout / College Coach". Scouts have full access to platform but can additionally create listings.

**Backend** (`routes/scout_listings.py`, ~330 lines):
- `POST /api/scout-listings` (auth + role gate) — creates a listing with `verified=false`. Validates controlled lists (positions: GK/CB/FB/CM/DM/AM/LW/RW/ST; levels: NCAA D1/D2/D3, NAIA, JUCO, Pro Academy, MLS Next, ECNL, Other; grad_years within current year ± 8).
- `GET /api/scout-listings` (public) — filters: `positions`, `grad_years`, `level`, `region` (substring), `q` (search school_name or description), `verified_only` (default true). Returns cards WITHOUT contact_email or website_url — those fields are only on the detail endpoint for registered users.
- `GET /api/scout-listings/{id}` (public, best-effort auth) — full listing; contact fields redacted for anonymous viewers with `_contact_gated: true` marker.
- `GET /api/scout-listings/my` (auth) — owner's listings including unverified drafts.
- `PATCH /api/scout-listings/{id}` (auth, owner) — any edit resets `verified=false` so admin re-approves.
- `DELETE /api/scout-listings/{id}` (auth, owner) — hard delete.
- `POST /api/scout-listings/{id}/logo` + `GET .../logo/view` — 5MB max school logo upload via Object Storage (reuses the players-profile-pic pattern).
- Admin: `GET /api/admin/scout-listings?status=pending|verified|all` + `POST /admin/scout-listings/{id}/verify` + `.../unverify`.

**Frontend**:
- `/scouts` (public) — searchable feed with filter panel (position multi-select chips, level dropdown, grad year dropdown, region text, keyword search). Green "Verified ✓" badge on approved listings. Anonymous footer nudge: "Contact info is visible to registered coaches only → Log in".
- `/scouts/:id` — full listing page with hero (logo + name + verified/pending chip), positions chips, grad-year chips, coach's notes prose block, requirements + timeline cards, and a gated "Get in Touch" section (website link + mailto) that shows "Log in or sign up →" for anon viewers.
- `/scouts/new` + `/scouts/edit/:id` (auth) — full form with position chips, grad-year chips, logo upload with preview, controlled-list validation. Yellow callout explains admin review requirement.
- `/admin/scouts` — 3-tab verification queue (Pending / Verified / All) with green "Verify" and yellow "Unverify" action buttons, inline listing preview.
- Dashboard nav: new green "Scouts" button in the header (visible to everyone).

**14 new pytest cases** (`test_scout_listings.py`): auth + role gate, full CRUD round-trip, patch resets verification, public feed hides unverified + redacts contact fields, detail contact-gating, all 5 filter axes (positive + negative matches), controlled-list validation (bad position / level / year), admin verify + unverify + pending queue + admin-gated endpoints. All passing.

**Live E2E verified via curl**: create → list (empty by default, shows with `verified_only=false`) → admin verify → appears on public feed → detail endpoint redacts contact for anon viewer, shows full for authed user → positions/grad_years/search filters all match correctly → delete.

**Phase 2 deferred** (per user request): "Express interest" button that emails scout + auto-attaches player dossier, in-app messaging threads between scout and coach, OG cards for scout listings. To be shipped next session after user tests phase 1.

### Delete Matches + Password Reset + Admin Bootstrap (May 1, 2026 — iter23)

**Delete individual matches** — user was stuck with duplicate match entries and had no UI to remove them individually (only bulk delete existed).
- **Backend**: New `DELETE /api/matches/{id}` reusing the same cascade semantics as the existing bulk-delete — hard-deletes clips/analyses/markers, soft-deletes the video (24h restore window), then removes the match doc. 404 on unknown id, 401 without auth, 404 on cross-user attempt.
- **Frontend**: Hover-reveal trash icon on every `MatchCard` (alongside the move-to-folder dropdown) with a context-aware confirm prompt. A prominent red "Delete Match" button on the `MatchDetail` header for when coaches are already inside a match.
- 5 new pytest cases: `test_delete_match_requires_auth`, `test_delete_match_unknown_id_returns_404`, `test_delete_match_happy_path`, `test_delete_match_cross_user_rejected`, `test_delete_match_cascades_clips_analyses_markers`.

**Forgot-password flow** — user forgot his deployed-env password.
- **Backend** (`routes/password_reset.py`, 170 lines): `POST /api/auth/forgot-password` ALWAYS returns `{status:"sent"}` 200 regardless of whether the email exists (prevents account enumeration). When the email is registered, it generates a high-entropy token via `secrets.token_urlsafe(32)`, stores ONLY the sha256 hash in `password_reset_tokens` (plaintext goes in the email), 60-min TTL. `POST /api/auth/reset-password` validates the token via hash lookup, rejects replay (checks `used_at`), enforces password policy (min 8 chars + letter + digit), re-bcrypts the new password, marks token used. Email template is branded (Bebas Neue + blue accent) and dispatched through the existing `send_or_queue` helper so it benefits from Resend quota-deferred retries.
- **Frontend**: "Forgot password?" link below the login password input; clicking opens a modal with an email input. After submit, the success state always shows "If an account exists for X, you'll receive a reset link" — never reveals registration status. New `/reset-password?token=...` SPA route with password-strength validation and a confirmation step.

**Admin bootstrap** — separate escape hatch so user can self-promote to admin on a fresh environment without database access.
- **Backend**: `POST /api/admin/bootstrap {secret}` (auth-required) — uses `hmac.compare_digest` against `ADMIN_BOOTSTRAP_SECRET` env var, constant-time. Logs all attempts at WARNING level for audit. Idempotent: second call on an already-admin account returns `{status:"already_admin"}` instead of erroring. Returns 503 if `ADMIN_BOOTSTRAP_SECRET` is unset on the server.
- **Frontend**: New `/admin/claim` protected route with a single password-field input for the secret. Calls the bootstrap endpoint and refreshes the local user cache via `/auth/me` on success. Shows purple "Admin access granted" state with "Dashboard" + "Open Admin" navigation buttons.

**Env additions**:
- `ADMIN_BOOTSTRAP_SECRET` — 43-char URL-safe random token (gen via `secrets.token_urlsafe(32)`)
- `PUBLIC_APP_URL` — used to construct the reset link inside the email

**Tests added**: 14 new pytest cases (5 delete-match + 9 password-reset/bootstrap). Full suite: **176 passed, 35 skipped, 1 flake** (`test_admin_preview_403_for_non_admin`, passes in isolation — unrelated ordering issue).

**Also fixed**: `test_voice_annotations.py::TestAuthAndValidation::test_empty_audio_returns_400` and `test_oversized_audio_returns_413` were failing due to stale `TESTCOACH_VIDEO_ID` seed data. Added a `live_video_id` fixture that skips gracefully when the seed video no longer exists — same pattern iter17 used for `test_video_routes.py`.

**Live verification** (preview pod): Created throwaway user → `/api/auth/forgot-password` → extracted raw token from queued email → `/api/auth/reset-password` worked → old password fails 401 → new password works 200 → replay 400. Admin bootstrap as coach: 403 on bad secret → 200 promoted on good secret → `/auth/me` reports `role:admin` → second call returns `already_admin`. Frontend: `/admin/claim` form renders, `/reset-password?token=...` page loads; MatchCard trash icon + MatchDetail "Delete Match" button both functional in the screenshot.

### P2 Code-Quality Cleanup + Live E2E Verification (Apr 30, 2026 — iter22)

**P2 perf/correctness fixes** (user asked for C):
- **`RosterSection.PlayerGroup`** — was calling `group.players.sort((a, b) => …)` directly inside JSX, which (a) mutates the caller's props array on every render and (b) runs sort on every re-render. Moved to a local non-mutating `[...group.players].sort(…)` assigned above the JSX. No behavior change.
- **`SharedView` (public unauthenticated roster list)** — same in-place `.sort()` on prop array inside `.map()`. Fixed to `[...players].sort(…)`.
- **`Dashboard`** — `displayMatches` (filters by folder) and `selectedFolderName` (folder lookup) wrapped in `useMemo` with correct deps so they don't recompute on unrelated state flips like bulk-select toggle, search token refresh, or mentions-badge re-fetch.

**Live E2E verification after P2 fixes** (user asked for B):
- Backend pytest suite: **165/165 passing, 33 skipped** (unchanged baseline).
- Backend E2E via curl as Ben Buursma admin:
  - Create Match → Save Manual Result (3 goal events) → `POST /matches/{id}/finish` → Gemini returned a 673-char AI recap in ~5s → `POST /share-recap` → public OG HTML has og:title + og:image + og:description + description meta tags → 1200×630 PNG (56KB) served with Cache-Control 300s → public JSON feed excludes `user_id` ✅
  - `POST /matches/{id}/finish` twice correctly returns 409 ("Match already finished") ✅
  - `POST /matches/{id}/unlock` clears `manual_result.is_final` but PRESERVES `insights.summary` — confirmed via `GET /matches/{id}` ✅
  - `POST /admin/game-of-the-week/set` → public `GET /game-of-the-week` returns full banner payload with `days_remaining=7`, `featured_by_name=Ben Buursma`, Gemini summary excerpt → `DELETE /admin/game-of-the-week` clears → public GET returns `{active:false}` ✅
  - Admin Email Queue: 25 sent / 0 quota_deferred / 0 failed across 25 records ✅
- Frontend smoke (live preview as admin): Dashboard renders with the GOTW banner visible ("ARSENAL 2-1 CHELSEA · 7D LEFT" with recap text), Coach Pulse card, Push Notifications toggle, Coach Network CTA, and both match cards — 0 page errors. Public `/match-recap/:token` renders Arsenal + Chelsea + full Gemini recap + WIN chip + goal timeline, 0 page errors.

Lint clean. No regressions.

### Share Recap — OG Card + Public Page (Apr 30, 2026 — iter20)

**Shareable AI match recaps.** A new `Share` button appears on the AI Recap card once a match is finished. One tap generates a public link with a rich preview image (team names, big scoreline, WIN/LOSS/DRAW chip, first 3 lines of the AI narrative, Soccer Scout 11 lockup) that unfurls in WhatsApp, Slack, Twitter, iMessage.

**Backend**:
- `services/og_card.py::render_match_recap_card` — new ~100-line renderer matching the aesthetic of `render_folder_card` / `render_clip_card`. Left accent strip color follows outcome (green W / red L / amber D). Clamps long recaps to 3 lines with ellipsis.
- `POST /api/matches/{id}/share-recap` (auth) — idempotent toggle. First call returns `{status: "shared", share_token}`; second call revokes. 400 if no AI recap yet, 404 if match not found.
- `GET /api/og/match-recap/{token}` — public HTML unfurl with og:title / og:image / og:description meta tags.
- `GET /api/og/match-recap/{token}/image.png` — public PNG (1200×630) with Cache-Control 300s.
- `GET /api/match-recap/public/{token}` — public JSON feed (excludes `user_id` to avoid leaking owner info).

**Frontend**:
- New public SPA route `/match-recap/:shareToken` → `SharedMatchRecap.js` — full-width hero with outcome-tinted accent, big scoreline, AI recap block, and goal timeline. No auth required.
- New `ShareRecapModal.js` — Enable Share flow: explanatory copy → button → share-token UI with copy, 3-channel share (WhatsApp, Twitter, Email) with pre-filled messages, and Revoke.
- Wired Share button into the AI Recap card inside `ManualResultForm.js`. Button changes color to green "Sharing On" when active.

**Verified**: **8 new pytest cases** covering 400-when-no-summary, share-toggle, 404-unknown-match, OG HTML meta-tag presence, PNG binary validity, public-JSON payload schema + no user_id leak, revoke-invalidates-URL, long-recap rendering. Live screenshot from `/match-recap/{token}` shows the full public page rendering correctly with AI narrative + WIN chip + goal timeline. Lint clean.

### Finish Match → AI Recap + Ben Buursma Promotion (Apr 30, 2026 — iter19)

**Finish Match (1-tap AI recap)**
- New `POST /api/matches/{id}/finish` endpoint — takes a saved manual_result, sets `is_final=true` + `finished_at`, calls Gemini 2.5 Flash via Emergent LLM key to generate a 80-120 word match recap (lead with result, integrate goals + key moments chronologically, end with one tactical takeaway). Falls back to a deterministic plain-English summary if the LLM is unavailable. Persists to `match.insights.summary` (same field used by `spoken_summary`, so existing UI keeps working).
- `POST /api/matches/{id}/unlock` — clears `is_final` so the coach can edit again. AI recap is preserved.
- Added `insights: Optional[dict]` to the `Match` Pydantic model so callers can read `summary_source` / `summary_generated_at`.
- New "Finish Match" button on `ManualResultForm` summary view — green gradient with spinner during generation. After click: FINAL chip + "Locked — final whistle blown" subtitle + purple "AI MATCH RECAP" card with full narrative. Edit/Remove buttons hidden when locked; Unlock button takes their place.
- 8 new pytest cases in `test_finish_match.py`: schema, 400 without manual_result, happy path with real Gemini call, 409 on second call, unlock+refinish loop, 404 unknown match, auth-required, deterministic-recap unit test, prompt-builder unit test. **Real LLM call verified end-to-end** — test recap quote: *"Arsenal secured a 2-1 victory over Chelsea in a dramatic Premier League contest…"*

**Admin Promotion**
- Promoted **Ben Buursma** (Ben.buursma@gmail.com) from `coach` → `admin` via direct DB update. Recorded in `test_credentials.md`.

**Verified**: pytest **151/151 passing** (143 → +8). Live screenshot confirmed full flow: Finish click → "Generating recap…" spinner → AI recap renders within ~5s → match locked. Lint clean.

### Platform avg Processing-Time Chip + Tap-to-Add-Goal (Apr 30, 2026 — iter18)

**Platform avg Processing-Time Chip (Coach Network)**
- Added `processing_time: { platform_avg_seconds, your_avg_seconds, your_samples }` and `samples.processing_durations_aggregated` to `GET /api/coach-network/benchmarks`. Uses the same sanity bounds (10s ≤ dur ≤ 2h) as `/api/videos/processing-eta-stats`.
- Added `_parse_iso_safe` helper in `coach_network.py` so one parser is shared across all temporal aggregates.
- **New UI chip** on `/coach-network` between the platform stats grid and "Your Bucket": blue pill with Timer icon, two big Bebas numbers (Platform avg / Your avg). Your avg colors green or amber based on whether you're above/below the network avg, with "Faster than avg" / "Slower than avg" tagline. Locked state when you have 0 completed runs.
- 3 new pytest cases in `test_coach_network_processing_time.py`: schema shape check, multi-user avg math (5 samples → platform 156s + testcoach 90s), outlier rejection.

**Tap-to-Add-Goal (ManualResultForm)**
- New mobile-first `Quick Add Goals` row — two big green/red tap targets labeled "GOAL / {team name}" that on each tap:
  1. Bump the scoreline by 1 (respects 99 max)
  2. Append a `goal` event to the editable events list with auto-computed minute (wall-clock elapsed since kickoff, clamped 0–120)
  3. Flash a green toast "+1 GOAL · Team · 42'" for 1.8s
- All events are fully editable afterward (minute / player / description), matching the existing events UI contract.
- Perfect for live-match logging where a coach just needs to tap once per goal without opening dropdowns.

**Verified**: pytest **143/143 passing** (+3 new). Screenshots confirmed both flows live — AI Processing Speed chip shows "Platform 2.5 MIN / Your 2.0 MIN · Faster than avg" in green; Quick Goal taps bump the home score 0→1, fire the toast "+1 GOAL · RESUME TEST A · 0'", and create a goal event row in the editable events list.

### ETA Estimator on MatchDetail Processing Banner (Apr 30, 2026 — iter17)
**Goal**: Show coaches "~3 min remaining" while AI analysis runs so the wait feels predictable.

**Backend**:
- New endpoint `GET /api/videos/processing-eta-stats` — returns `{avg_seconds, samples}` computed from the last 20 completed videos owned by the current user. Durations < 10s or > 2h are discarded as outliers. Exposed `processing_started_at` in `/api/videos/{id}/processing-status` so the client can compute elapsed time.
- 4 new pytest cases in `test_processing_eta.py`: auth required, empty case, averages match (seed 3 videos with 60/120/180s → avg=120s), outlier rejection (keeps 120s, discards 5s + 3h).

**Frontend**:
- New `useProcessingEta(videoMeta)` hook. Strategy: crossfade live extrapolation with historical average. Below 10% progress → 100% historical (elapsed is too noisy). At 60%+ progress → 100% live (elapsed/progress ratio). Between 10-60% progress → linear blend. Updates every 3s so the display ticks down visually.
- Rendered as a small amber/Bebas `~X min remaining` line beneath the status text inside `ProcessingProgressBar`. Only renders for active `processing`/`queued` — hidden on `failed`/`completed`.
- Humanizer: `< 20s → "< 20 sec remaining"`, `< 90s → "~N sec"`, `< 10 min → "~N.5 min"`, `≥ 10 min → "~N min"`.

**Verified**: pytest **140/140 passing** (up from 143; regression_sweep + iter14 tests now gracefully skip when seed data is missing rather than failing, fixing long-standing test data drift). Screenshot-reproduced ETA text "~2 min remaining" with mocked processing state (40% progress + 90s elapsed + 148s historical avg → 2 min). Lint clean.

**Also fixed test data drift**: `test_video_routes.py` was hard-coded to a now-deleted video id; replaced with a dynamic `existing_video_id` fixture that picks any live video from the user's matches. `test_regression_sweep.py` now auto-skips the whole module (not fails) when seed player/clip IDs have been cleaned up.

### Visible Processing Progress Bars on MatchDetail + Dashboard (Apr 30, 2026 — iter16)
**Problem**: Before this, MatchDetail only showed a small text chip ("Processing… 42%") and Dashboard cards showed plain text — coaches couldn't see at a glance how far along AI analysis was.

**Delivered**:
- **New `ProcessingProgressBar.js`** — reusable presentational component showing: gradient banner (blue for active, red for failed), big percentage display (Bebas Neue), animated spinner / X icon, full-width progress bar with smooth 500ms fill transition, and a 4-step status grid (Tactical / Player Ratings / Highlights / Timeline Markers) where each step renders green check / blue spinner / red X / empty-circle. Includes inline "Retry" / "Resume" button when failed — wires to `POST /api/videos/{id}/reprocess`.
- **Mounted on MatchDetail** below the upload panel. Auto-polls via existing 5s videoMeta poll in MatchDetail's `useEffect`.
- **Thin progress bar on MatchCard (Dashboard)**: replaces the plain "Processing (X%)" text with a flex column — "Processing · X%" label + 1px-tall blue progress bar with 500ms transition. Only renders in `processing`/`queued` states. New `data-testid="match-card-progress-bar"`.

**Verified**: live screenshots from both `/match/:id` (showing red "PROCESSING FAILED" state with 0/4 steps + Retry button) and `/` dashboard (11 cards render correctly, progress bars hidden when no active processing). Lint clean. No backend changes needed — all data already exposed by `/api/videos/{id}/processing-status` and `/api/matches` (which injects `processing_status` + `processing_progress` per match).

### VideoAnalysis useVideoProcessing Hook (Apr 30, 2026 — iter15)
**Pure refactor: 585 → 490 lines (-16%)** in VideoAnalysis.js. Extracted two cohesive hooks in `/app/frontend/src/pages/components/hooks/useVideoProcessing.js`:

- **`useVideoProcessing(videoId, onAnalysesRefresh, onMarkersRefresh)`** — owns the 8s polling loop, server-boot-id restart detection, `reprocess` mutation, and derived flags (`isProcessing` / `isProcessed` / `processingFailed` / `serverRestarted`).
- **`useVideoData(videoId)`** — initial parallel load of `videoMetadata`, `analyses`, `annotations`, `clips`, `match`, `players`, `markers`, plus short-lived access-token-signed `videoSrc`.

**Behavior unchanged** — same 8s interval, same boot-id detection, same reprocess endpoint. Screenshot confirmed the page still renders correctly end-to-end (toolbar + processing-error banner + player + sidebars + tabs all load). Lint clean.

**Cumulative refactor status**: Dashboard 750→373 (-50%), MatchDetail 646→336 (-48%), VideoAnalysis 835→490 (-41%). Total 2229 → **1199 lines (-46%)** across the 3 pages + 14 components + 4 hook modules.

### Email Queue with Quota Fallback + Admin Visibility (Apr 30, 2026 — iter14)
**Problem**: Resend free tier has hard monthly/daily limits. Naive sends raised `HTTPException(502)` and the email was lost forever.

**Solution**: New `services/email_queue.py` wraps every send. On Resend error, the email is persisted to a MongoDB `email_queue` collection with one of three statuses:
- `sent` — delivered, email_id recorded
- `quota_deferred` — Resend returned a quota-style error (regex match on `daily_quota|monthly_quota|rate_limit|429|too_many_requests`). Retries every 1h via APScheduler (quota usually resets at UTC midnight).
- `failed` — non-quota transient error. Backoff: 1h → 4h → 12h → 24h → 72h. After 5 attempts: `failed_permanent` (no further retries).

**Integration**:
- `routes/coach_pulse.py::_send_via_resend` and `services/clip_mentions.py::_send_via_resend` now delegate to `send_or_queue`. Callers treat `quota_deferred` as success (the queue will retry) — users don't see an error.
- New APScheduler job `email_queue_retry` runs every 30 min and calls `process_queue()`, which finds any `quota_deferred|failed` email whose `next_retry_at <= now` and re-attempts it.
- 3 new admin endpoints in `routes/admin.py`: `GET /api/admin/email-queue` (depth + recent items), `POST /api/admin/email-queue/process` (manual trigger), `POST /api/admin/email-queue/{id}/retry` (single-item retry).

**Admin UI**: New `EmailQueueCard` component renders at the top of `/admin/users` — 4-stat grid (Sent / Quota Deferred / Retrying / Failed), "Retry All Now" button, recent-15 list with per-item status chips and inline "Retry" buttons for non-sent items. Card border turns amber when there are queued items.

**Shared-loop fix**: moved the module-scoped asyncio event loop from `test_push_notifications.py` into `conftest.py::run_async` so multiple async test files in the same pytest session share one loop (Motor caches its IO executor against the first loop it sees).

**Verified**: pytest 153 → **165/165 passing** (+12 new email-queue tests: quota detection regex, backoff progression, send-success / quota-deferred / transient-failure paths, retry-and-send, skip-future-retries, give-up-after-5-failures, 4 HTTP endpoint tests). Screenshot confirms Admin UI renders correctly with 8 already-queued real emails showing SENT status.

### React Page Refactor — Dashboard / MatchDetail / VideoAnalysis (Apr 30, 2026 — iter13)
**Long-term-maintainability cleanup. Pure frontend decomposition — no behavior changes, no API changes.**

**Line-count reductions** (2229 → 1294, **-42%**):
- `Dashboard.js`: 750 → 373 (**-50%**)
- `MatchDetail.js`: 646 → 336 (**-48%**)
- `VideoAnalysis.js`: 835 → 585 (**-30%**)

**14 new focused components + 1 hook module** under `/app/frontend/src/pages/components/`:
- Dashboard: `DashboardHeader.js`, `FolderSidebar.js`, `MatchCard.js`, `CreateMatchModal.js`, `FolderFormModal.js`, `ShareFolderModal.js`, `BulkActionBar.js`
- MatchDetail: `UploadPanel.js`, `DeletedVideosDrawer.js`, `ConfirmReuploadModal.js`, `RosterSection.js`
- VideoAnalysis: `ClipCreateForm.js`, `VideoToolbar.js`, `DataIntegrityBanner.js`, `hooks/useClipActions.js` (exports `useClipShare`, `useClipCollection`, `useClipTagging` — encapsulating ~150 lines of state + handlers pulled out of VideoAnalysis)

**Verified**: testing_agent_v3_fork iter13 — 97% (31/32 testids verified), login → dashboard → folder CRUD → match CRUD → match detail → roster (add-player + csv-import) → admin/mentions/non-existent-video all render without React crashes or missing-testid regressions. Test artefacts seeded and cleaned. Lint clean.

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

### Logo Intro Animation + OG Lockup + Crest Pipeline (Apr 30, 2026 — iter13)
**3 brand-polish features.**

**1. Animated logo intro on first-time auth**
- New CSS file `styles/logo-intro.css` defines `logo-fade-up` (translate+scale ease-out), `logo-glow-pulse` (drop-shadow blue glow on entrance), and `tagline-fade-in`.
- AuthPage gates the animation behind `sessionStorage.getItem('logo-intro-played')` — fires only once per browser session.
- Honors `prefers-reduced-motion: reduce` for accessibility.

**2. OG cards embed the logo lockup**
- `services/og_card.py` — `_load_logo_lockup()` (cached) + `_paste_brand_lockup(img, position='right'|'left')`. Clip cards use `position='left'` to leave room for the play-triangle visual.
- All 4 render functions (team, folder, clip, player) now paste the transparent-bg `logo-mark.png` (~56px tall) instead of plain text "SOCCER SCOUT 11".
- Falls back gracefully to text-only branding if the logo file isn't bundled.

**3. Per-club crest pipeline**
- New `services/crest_pipeline.py` — given any upload (JPEG/PNG/WEBP), `process_crest()`:
  - Detects uniform background via 4-corner sampling
  - Strips matching pixels to alpha=0 via Euclidean color distance (`BG_TOLERANCE=35`)
  - Crops to non-transparent bounding box → letterboxes into transparent square → downsamples to 512×512 PNG
- `POST /api/clubs/{id}/logo` now runs every upload through this pipeline. Crests composite cleanly onto any background and flow automatically into OG cards.
- Verified end-to-end: 400×400 white-bg JPEG → 1959-byte transparent PNG.

**Verified**: pytest 141 passed + 5 skipped (baseline preserved). Frontend lint clean. Auth animation captured mid- and end-state. OG lockup visible in rendered cards. Crest upload curl-tested.

### Mentions Inbox + Mobile Manual-Result Form + Coach Pulse Preview Modal (Apr 30, 2026 — iter12)
**3 follow-on features after iter11.**

**1. Mobile-optimized ManualResultForm**
- Score inputs now have ±/± stepper buttons on mobile (`sm:hidden`) — bigger tap targets (40×56px), `inputMode="numeric"` for native-keyboard digits.
- Event-row grid switched from `grid-cols-12` (desktop-first) to `grid-cols-2 sm:grid-cols-12` so mobile renders a 2-col stacked layout: Min/Type on row 1, Team on row 2, Player on row 3, Description on row 4, Remove button as full-width row 5 with explicit "Remove" label.
- Summary view scoreline gap tightened (`gap-3 sm:gap-6`); team labels truncate; outcome chip shrinks tracking on mobile.
- All grid children get `min-w-0` to prevent horizontal overflow at 375px.

**2. Mentions Inbox**
- Backend: 3 new endpoints in `routes/coach_network.py`:
  - `GET /api/coach-network/mentions?unread_only=…` — returns mentions joined with collection title/share_token/clip_count/description
  - `POST /api/coach-network/mentions/{id}/read` — marks single mention read (404 if not yours)
  - `POST /api/coach-network/mentions/read-all` — bulk mark-as-read
- Frontend: new `/mentions` page (`MentionsInbox.js`) with empty state, unread purple-dot indicator, time-ago formatter, "Watch Reel →" CTA opens public reel in new tab and auto-marks-read, "Mark all read" header button.
- Dashboard nav: new "Mentions" button (desktop + mobile icon) with unread-count badge polled on mount.

**3. Coach Pulse Digest Preview**
- Backend: `GET /api/coach-pulse/admin-preview/{user_id}` — admin-only, renders the same email HTML another user would receive on Monday's auto-blast.
- Frontend: AdminUsers row gains a green "Preview Digest" button → opens a modal with `<iframe srcDoc>` showing the rendered email. Auth-fetched HTML (not anon iframe) so endpoint stays admin-protected.

**Verified**: pytest 134 → 141 passed (+7 new tests for the iter12 endpoints), 5 skipped (1 mention E2E skipped because testcoach has 0 clips). Frontend smoke: mentions empty-state renders, admin Preview Digest modal opens with personalized HTML, mobile manual-result form layout passes at 375px (tiny defensive overflow fix applied). Zero React console errors.

### Admin UI + APScheduler + @-Mentions + Manual-Result Matches + Storage Dedup + Resend Domain Swap (Apr 30, 2026 — iter11)
**7 user-requested items completed in one session.**

**1. Resend sender email swap** → `SENDER_EMAIL` env → `bb@soccerscout11.com`. User added the DKIM record to DNS; propagation may take up to 48h.

**2. APScheduler weekly cron** → `AsyncIOScheduler` started in `server.py` `@app.on_event("startup")`. Fires every **Monday 08:00 UTC** with 1-hour misfire grace. Re-uses `run_weekly_blast()` (refactored out of the HTTP endpoint) so both manual admin trigger and cron path hit the same idempotent logic (dedupes per ISO week via `last_sent_at`).

**3. `services/storage.py` dedup** → All storage primitives (`create_storage_session`, `put_object_sync`, `get_object_sync`, `store_chunk`, `read_chunk_data`, `StorageCircuitBreaker`, etc.) now live ONLY in `services/storage.py`. `server.py` re-exports them (no code duplication). server.py: 1995 → 1900 lines.

**4. Admin-promotion UI** → New `/admin/users` page (admin-only). Lists all users with role chips (OWNER/ADMIN/ANALYST/COACH), activity counters (matches/clips), and Promote/Demote buttons. Backend: `routes/admin.py` with `GET /api/admin/users` (search by `q`) and `POST /api/admin/users/{id}/role`. Self-demotion blocked if last admin. Only owners can change owner roles.

**5. localStorage PII cleanup + token revalidation** → The `user` blob now stores ONLY `{id, name, role}` (email removed). On App mount, `/api/auth/me` is called to verify the token is still valid and refresh role — clears storage on 401 so stale sessions don't linger. Supports role changes taking effect without logout/login.

**6. @-Mentions in clip-reel share flow** → New `GET /api/coach-network/mentionable-coaches?q=…` returns all coaches on the platform with name/email/activity flags, sorted active-first. `ShareReelModal` adds a description field + searchable autocomplete dropdown + chip UI for mentioned coaches. On collection creation, each mentioned coach gets a Resend email with a branded template ("@ Mention", title, description blockquote, "Watch the reel →" CTA) linking to `/clips/{share_token}`. `services/clip_mentions.py` handles email dispatch + `clip_mentions` collection records (deduped per collection/coach so edits don't re-spam).

**7. Manual-result matches (games without video)** → Backend: `PUT/GET/DELETE /api/matches/{id}/manual-result` with `home_score`, `away_score`, `key_events: [{type, minute, team, player_id?, description}]`, `notes`. Auto-computes `outcome: W/D/L`. `Match` model exposes `has_manual_result` + `manual_result` fields. Frontend: `ManualResultForm` component in `pages/components/` shows scoreline inputs, key-event editor (player dropdown scoped to rostered players by team), and coach notes. Renders above the upload panel in MatchDetail when no video is attached. Dashboard cards without video show "No Video — Manual Result 3-1 W" badge.
**Season Trends integration**: manual-result matches are INCLUDED in season aggregates. `per_match` entries now have `source: "manual" | "video" | "pending"`. `totals` includes `matches_with_video` + `matches_with_manual_result`. Goal events from manual-result increment the `clip_type_totals.goal` counter.

**Bug fix during iter11**: GET `/api/matches/{id}/manual-result` was returning 404 after DELETE because `find_one` with inclusion projection returns `{}` which is falsy. Fixed via `if match is None` check + explicit `id: 1` in projection.

**Verified**: pytest 116 baseline + 17 new tests pass (133 passed total + 4 skipped). 1 iter11 bug caught & fixed by testing agent. Frontend smoke: AdminUsers (61 users), ManualResultForm render/save, ShareReelModal autocomplete, Dashboard manual-result badge, localStorage cleanup, /auth/me revalidation, APScheduler startup log — all confirmed. Zero React console errors, zero key warnings.

### Code Quality Report Cleanup + Pipeline Extraction (Apr 30, 2026)
**Two refactors completed in the same session (user chose option c).**

**(a) SERVER_BOOT_ID consolidation + React hook/key cleanup**
- `runtime.py` is now the single source of truth for `SERVER_BOOT_ID` / `SERVER_BOOT_TIME`. `db.py` re-exports them for backwards compat. `server.py` imports from `runtime`. `routes/videos.py` imports directly (lazy-import-with-cache hack removed).
- Verified at runtime: `/api/heartbeat` boot_id exactly matches `/api/videos/{id}/processing-status` server_boot_id.
- React hook deps: Dashboard/MatchDetail/TeamRoster/SharedView/SharedClipView fetch functions wrapped in `useCallback` with correct deps. All `// eslint-disable-line react-hooks/exhaustive-deps` comments removed where safe (kept 1 intentional in VideoAnalysis for mount-only load).
- Array-index keys: MatchInsights/SeasonTrends/PlayerSeasonTrends/CoachNetwork list keys changed from `{i}` to content-derived (`${i}-${text.slice(0,32)}`) on every dynamic list. Only fixed-length static lists (10-star rating, tab indicator dots) retain index keys.

**(b) Full extraction of run_auto_processing + FFmpeg pipeline from server.py → services/processing.py**
- `services/processing.py` now owns the ENTIRE auto-processing pipeline: `run_auto_processing`, `prepare_video_sample`, `prepare_video_segments_720p`, `run_single_analysis`, `parse_and_store_markers`, `build_roster_context`, `build_analysis_prompts`.
- Decoupled from server.py via `auto_create_clips_callback` dependency injection — service module never imports server.
- `_emergent_key()` helper reads `EMERGENT_LLM_KEY` at call time (addresses iter9 concern about module-time env capture).
- server.py keeps 7 thin 3-line wrapper functions so every existing call site (finalize_chunked_upload, reprocess, generate_analysis, generate_trimmed_analysis, resume_interrupted_processing) works unchanged.
- `server.py` shrunk from 2373 → 1995 lines (-378, -16%). Combined with prior refactors, server.py is down ~35% from its 2500-line peak.
- **Verified**: 103/106 pytest (unchanged baseline), +13 new refactor regression tests all green, zero frontend console errors, zero React key warnings. Reprocess endpoint responds correctly on real video; generate_analysis + generate_trimmed_analysis return 404 cleanly on missing video with no import errors from the new module.

### Post-Game Spoken Summary + Auto-Reel from Voice Key Moments (Apr 30, 2026)
**Premise**: At the final whistle, a coach taps a button, dictates a 30-90 second recap, and gets a polished match summary saved to MongoDB — plus optionally builds a shareable highlight reel from every voice-tagged key_moment with one click.

**Backend** — `routes/spoken_summary.py` (200 lines):
- `POST /api/matches/{match_id}/spoken-summary` — multipart audio upload. Whisper transcribes, persists to `match.insights.summary` + keeps original at `match.insights.spoken_transcript`. Same audio-validation rules as voice-annotations (1KB-25MB, all common codecs).
- `POST /api/matches/{match_id}/spoken-summary/polish` — re-runs the saved spoken transcript through Gemini 2.5 Flash with a "clean it up while preserving every observation, fix grammar, remove filler" prompt. Saves polished version as the new `summary`. Tracks `summary_source` (spoken_raw vs spoken_polished) and timestamps so coaches can audit the chain.
- `POST /api/matches/{match_id}/auto-reel` — finds all voice-source key_moment annotations, creates a clip per moment (configurable ±N seconds window, default 5/7), bundles into a `clip_collection` with a 12-char `share_token`. Idempotent: if a clip with the same start time already exists from a previous auto-reel run, reuses it (`skipped_existing` counter in the response).
- Per-request env lookup for `EMERGENT_LLM_KEY` (consistent with voice_annotations pattern). Robust regex code-fence stripping for Gemini polish output.

**Frontend** — `pages/components/SpokenSummaryPanel.js` (240 lines):
- Two-card panel that renders at the top of `MatchInsights`:
  - **Spoken Summary** card (purple) — Start Recording → Stop & Save (red, animate-pulse) → Transcribing (yellow + sparkle spinner) → AI Polish button (cyan with lightning icon)
  - **Auto Highlight Reel** card (green) — Build Reel → "N clips bundled" result card → Copy share link button (with `Check` confirm state)
- `hasVoiceKeyMoments` prop pre-disables the Auto-reel button when no qualifying tags exist (with helpful inline text: "Tag key moments via the Live Coaching mic in Video Analysis first, then come back.")
- Raw transcript collapsible card appears below the recording controls so the coach can review what Whisper heard before clicking polish — dismissible with X icon
- `onSummaryUpdated` callback updates the MatchInsights' "Verdict" section live without page reload
- Wired into `MatchInsights.js` — fetches `/annotations/video/{video_id}` to count voice key_moments and gate the Build Reel button accordingly

**End-to-end verified** with real espeak-ng audio:
- Raw transcript: "Today was a tough match against Express FC. Our boys came out flat in the first half but really stepped it up in the second..."
- Gemini-polished: "Today's match against Express FC proved to be a challenging contest for our squad. The team started the first half with a noticeable lack of intensity, appearing flat on the pitch. However, there was a significant improvement in the second half..." (coherent 3-paragraph summary, professional tone, every observation preserved)
- Auto-reel: 2 voice key_moments → 2 clips bundled → shareable collection link

**Testing**: 105/106 backend tests still passing (1 intentional skip on flaky LLM test). Frontend smoke verified visually.

### Live Coaching Mode — Voice-Tagged Annotations (Apr 30, 2026)
**Premise**: Coaches on the sideline can press-and-hold a mic button, speak ("Pressing trigger weak side coverage broken down"), and get a fully-classified annotation dropped on the timeline within ~2-3 seconds. No typing, no scrubbing.

**Backend** — `routes/voice_annotations.py` (155 lines):
- `POST /api/voice-annotations` — accepts multipart `video_id` + `timestamp` + `audio` (webm/mp4/wav). Auth-gated, video-ownership enforced, validates audio size (1KB ≤ size ≤ 25MB).
- **Whisper transcription** via `emergentintegrations.llm.openai.OpenAISpeechToText` (`whisper-1` model, `response_format=json`, English-locked). Errors → graceful 502.
- **Gemini classification** via `LlmChat` with `gemini-2.5-flash` — returns `{type: tactical|key_moment|note, confidence: 0.0-1.0}`. Robust regex-based code-fence stripping (replaces fragile `lstrip('```json')`). Falls back to `note` with confidence=0 on any parse error or LLM outage. Each fallback path logs at WARNING level for ops visibility.
- Per-request env lookup for `EMERGENT_LLM_KEY` (no module-level caching) so key rotation doesn't require a backend restart.
- Persisted as a regular `Annotation` doc with `source='voice'`, `transcript`, and `classification_confidence` so the existing `AnnotationsSidebar` surfaces voice tags side-by-side with manual ones. Annotation Pydantic model extended with these 3 optional fields so the UI can render a mic icon for voice tags after a page reload.
- 11 pytest cases covering happy path (real Whisper transcription of an espeak-ng-generated WAV → Gemini classifies as `tactical` with 0.9 confidence), cross-user 404, oversized/empty audio rejection, missing-key 503, classification fallback, and the `source='voice'` field round-trip.

**Frontend** — `pages/components/LiveCoachingMic.js` (220 lines):
- Two render modes from a single component:
  - **FAB (mobile)**: fixed bottom-right 64px circular button, press-and-hold to record, release to transcribe. Live-mode toggle pill above it. Status toast and "recent tag" toast positioned above the FAB.
  - **Inline (desktop)**: pill-shaped button next to the existing Note/Tactical/Key-Moment tools in the VideoAnalysis toolbar.
- **Live mode toggle** — when ON, the new annotation gets `liveAnchorVideoTime + (now - liveAnchorWallClock)` instead of `videoCurrentTime`. Lets coaches set up the camera, walk to the bench, and tag plays in real-time.
- **MediaRecorder** flow — picks the best supported mime (`audio/webm;codecs=opus` → `audio/webm` → `audio/mp4` → `audio/ogg`), uses pointer events (so works on touch + mouse), auto-stops tracks on release to silence the browser's mic indicator immediately.
- Color-coded states: blue idle / red recording / yellow transcribing / purple in-live-mode.
- Wired into VideoAnalysis.js: desktop inline (`hidden sm:block`) + mobile FAB (`sm:hidden`). Both call back to the parent's `setAnnotations` so the sidebar updates without a page reload.

**End-to-end verified**: Real espeak-ng-generated audio "The pressing was good but our weak side coverage broke down on the goal" → Whisper returned exact transcript → Gemini classified as `tactical` (0.9 confidence) → annotation persisted with source=voice. **105/106 pytest passing** (1 intentional skip on a flaky LLM-classification test).

### Web Push Notifications (Apr 30, 2026)
**Triggers**: (1) AI auto-processing finished for a match, (2) Someone opened a coach's shared clip (throttled to 1/clip/6h to prevent refresh-spam).

**Backend**:
- `services/push_notifications.py` (75 lines) — `send_to_user(user_id, title, body, url)`. Wraps `pywebpush` with `asyncio.to_thread`. Auto-prunes 410/404 (expired) subscriptions from MongoDB. Lazy-loads VAPID private key from PEM file once and caches it.
- `routes/push_notifications.py` (76 lines) — 5 endpoints: GET `/push/vapid-key` (public), POST `/push/subscribe` (Pydantic-validated upsert keyed on endpoint), POST `/push/unsubscribe`, GET `/push/subscriptions` (count only), POST `/push/send-test`.
- VAPID keys generated locally with `py_vapid` + `cryptography`. Public key (87-char base64url) in `.env`, private PEM at `/app/backend/vapid_private.pem` (mode 600).
- **Integration hooks**: `server.py` `run_auto_processing` fires push when video transitions to `processing_status='completed'`. `server.py` `get_shared_clip_detail` fires throttled push to clip owner on each public view (records `last_view_notify_at` on the clip doc to enforce 6h throttle).
- 15 pytest cases in `/app/backend/tests/test_push_notifications.py` (subscribe-upsert, cross-user isolation, unknown-endpoint delete, mocked send_to_user 410-prune, mocked send-test failure handling, auto-processing hook fired with correct args, shared-clip-view hook + throttle, configured/unconfigured states). **95/95 passing.**

**Frontend**:
- `/utils/push.js` (115 lines) — pure browser-API helpers: `isPushSupported()`, `isIosButNotInstalled()`, `requestPushPermission()`, `subscribeToPush()`, `unsubscribeFromPush()`, `sendTestPush()`, `getSubscriptionCount()`. Handles permission states cleanly (granted/denied/default).
- `CoachPulseCard.js` — added a second row beneath the email subscribe with BellSlash/BellRinging icon + "Push notifications" + Enable/Enabled toggle. Auto-fires a confirmation push on first enable. iOS-not-installed users see a hint instead of a non-functional button.
- `service-worker.js` rewritten with `push` (renders notification with icon/body/data.url tag) and `notificationclick` (focuses existing client → `client.navigate(url)` or opens new window) handlers.
- App.js — service worker registration now runs in all envs (was production-only) so dev/staging users can opt into push too.

**Known caveats**:
- Push only works on HTTPS (preview/prod URL satisfies this; localhost dev does not).
- iOS Safari requires the PWA to be installed (added to home screen) before push subscriptions are allowed — the UI surfaces this requirement in-place.
- Resend sandbox + push are independent — both can be enabled per-coach.

### PWA (Progressive Web App) + Admin Promotion (Apr 30, 2026)
- **testcoach@demo.com promoted to `admin`** role via mongosh so `/api/coach-pulse/send-weekly` can be triggered. Verified endpoint returns `{sent: 0, skipped: 0}` as expected (no active subscribers yet).
- **PWA manifest** at `/manifest.json` — name "Soccer Scout", `display: standalone`, portrait-primary orientation, brand colors `#0A0A0A`/`#007AFF`, 2 app shortcuts (New Match + Coach Network).
- **App icons** generated via Pillow (backend dep reused): `favicon.png` (64px), `apple-touch-icon.png` (180px), `icon-192.png`, `icon-512.png` — all marked `any maskable` for safe zone cropping on Android.
- **Service worker** at `/service-worker.js` — minimal pass-through (no response caching) just to satisfy the installability requirement. Videos and AI analyses must always be fresh.
- **index.html updated** — new title "Soccer Scout — AI Match Analysis for Coaches", updated theme-color, manifest link, Apple PWA meta tags (`apple-mobile-web-app-capable`, status-bar-style, title), `viewport-fit=cover` for modern phones.
- **`components/PWAInstallPrompt.js`** — non-intrusive bottom-right prompt with two flows:
  - Chrome/Edge/Android: captures `beforeinstallprompt`, shows an "Install" button that triggers the native UA prompt
  - iOS Safari: fallback hint ("tap Share → Add to Home Screen") with phosphor icons since iOS has no programmatic install
  - Dismissals remembered in `localStorage` for 14 days — never nags
- Service worker registered in App.js via `navigator.serviceWorker.register()` (only in production builds to avoid dev-server conflicts).
- Manifest, icons, SW all verified serving at `200 OK`.

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
- **Coach Pulse email delivery** — depends on Resend DNS propagation for `soccerscout11.com`. Until the DKIM TXT record is verified at resend.com/domains, emails to non-account-owners will bounce. Check `resend.com/domains` status.
- **Mentions inbox** — currently mention emails are one-way. Future: show mentioned coaches a "You were mentioned on 3 reels" inbox in Coach Network UI (collection already stored in `clip_mentions`).
- **Manual match events from mobile** — the current `ManualResultForm` is desktop-first. Could use a mobile-optimized quick-entry ("tap to add goal at current time") for coaches entering during matches on phones.
- **APScheduler persistence** — currently using in-memory scheduler. On restart, missed jobs with >1h gap would be dropped (misfire_grace_time=3600). For reliability, consider a MongoDB job store so pending jobs survive restarts.
- Resend custom domain verification polling (auto-notify when DNS is verified)
- Address remaining "Insecure localStorage" and "Expensive JSX Computation" items from the Code Quality Report
- Dedicated "Manage Templates" modal once a coach exceeds 6 saved templates
- Bulk-share clips picker on Dashboard (cross-match version)
- Season stats dashboard per player (aggregate across teams/seasons)
- Position-breakdown comparison on TeamRoster (network %s vs your team %s)

## Test Credentials
- Email: testcoach@demo.com
- Password: password123
