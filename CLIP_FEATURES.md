# Video Clipping & Highlights Features

## Overview
Added comprehensive video trimming/clipping and downloadable highlights packaging to the Soccer Scout platform.

## Features

### 1. Video Clip Creation
Users can create clips from any uploaded match video:
- **Set Start/End Times**: Manually input times or use "Now" button to capture current video timestamp
- **Clip Types**: Highlight, Goal, Save, Tactical Play, Mistake
- **Metadata**: Add title and description for each clip
- **Visual Timeline**: See current playback time while creating clips

### 2. Clip Management
- **View All Clips**: Sidebar displays all clips for the current video
- **Play Clips**: Click "Play Clip" to jump to start time and auto-pause at end time
- **Delete Clips**: Remove unwanted clips
- **Clip Details**: Shows duration, type, and description

### 3. Highlights Package Download
- **One-Click Export**: Download complete highlights package as JSON
- **Includes**:
  - Match information (teams, date, competition)
  - Video metadata
  - All clips with timestamps
  - AI analyses (tactical, player performance, highlights)
  - Generated timestamp
  
### 4. UI Components
- **Clip Tools Section**: Located below video player with create clip button and current time display
- **Create Clip Form**: Inline form with all clip properties
- **Clips Sidebar**: Shows all clips with play and delete actions
- **Download Highlights Button**: Bright green button for easy access

## API Endpoints

### Create Clip
```
POST /api/clips
Headers: Authorization: Bearer {token}
Body: {
  "video_id": "string",
  "title": "string",
  "start_time": float,
  "end_time": float,
  "clip_type": "highlight|goal|save|tactical|mistake",
  "description": "string" (optional)
}
```

### Get Clips for Video
```
GET /api/clips/video/{video_id}
Headers: Authorization: Bearer {token}
```

### Delete Clip
```
DELETE /api/clips/{clip_id}
Headers: Authorization: Bearer {token}
```

### Download Highlights Package
```
GET /api/highlights/video/{video_id}
Headers: Authorization: Bearer {token}
```

## Database Schema

### Clips Collection
```javascript
{
  id: string (UUID),
  video_id: string,
  match_id: string,
  user_id: string,
  title: string,
  start_time: float (seconds),
  end_time: float (seconds),
  clip_type: string,
  description: string,
  created_at: string (ISO timestamp)
}
```

## Usage Workflow

1. **Upload Match Video**: Go to match details and upload video
2. **Watch & Analyze**: Use video player to review match
3. **Create Clips**: 
   - Click "Create Clip" button
   - Set start time (or click "Now" at desired moment)
   - Play video and click "Now" at end moment
   - Add title and select type
   - Save clip
4. **Manage Clips**: View all clips in sidebar, play or delete as needed
5. **Export Highlights**: Click "Download Highlights" to get complete package

## Technical Details

### Frontend
- **Component**: `VideoAnalysis.js`
- **State Management**: React hooks for clips, clip form, timestamps
- **Video Control**: Uses video ref for playback control and time tracking
- **Auto-pause**: Event listener stops playback at clip end time

### Backend
- **Framework**: FastAPI
- **Database**: MongoDB (clips collection)
- **Authentication**: JWT-based with user ownership validation
- **Data Model**: Pydantic models for validation

## Future Enhancements
- Server-side video processing (ffmpeg) to generate actual video files
- Clip preview thumbnails
- Bulk clip operations
- Share clips with team members
- Export clips as individual video files
- Merge multiple clips into highlight reel
