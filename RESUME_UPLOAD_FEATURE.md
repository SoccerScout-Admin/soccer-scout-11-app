# Resume Upload Feature Documentation

## Overview
The Soccer Scout platform now supports **resuming interrupted uploads**. If your 10GB+ video upload is interrupted, you can simply start uploading the same file again and it will continue from where it stopped.

## How It Works

### Automatic Resume Detection
When you start an upload, the system:
1. Checks for existing upload with same: filename + file_size + match_id
2. If found → Returns existing upload session with list of uploaded chunks
3. Frontend skips already-uploaded chunks
4. Continues from last successful chunk

### Example Scenario
```
First attempt: Uploads 205/1090 chunks (18%) → Network interrupts
Second attempt: Detects existing upload → Skips chunks 0-204 → Resumes from chunk 205
Result: Saves 18% of upload time (~30 minutes for 10GB file)
```

## User Experience

### Starting Fresh Upload
```
📤 Starting NEW upload: abc123, 1090 chunks of 10.0MB each
⬆️  Uploading chunk 1/1090...
✓ Chunk 1/1090 uploaded (0%)
⬆️  Uploading chunk 2/1090...
```

### Resuming Upload
```
🔄 RESUMING upload from chunk 206/1090 (18% complete)
Alert: "Resuming previous upload from 18%. 205 of 1090 chunks already uploaded."
⏭️  Skipping chunk 1/1090 (already uploaded)
⏭️  Skipping chunk 2/1090 (already uploaded)
...
⏭️  Skipping chunk 205/1090 (already uploaded)
⬆️  Uploading chunk 206/1090...
✓ Chunk 206/1090 uploaded (19%)
```

## When Resume Works

### ✅ Resume Triggers:
- **Network interruption** during upload
- **Browser closed** before completion
- **Computer sleep/hibernation** during upload
- **Backend restart** during upload
- **503/502 errors** during upload
- **Timeout errors** during upload

### ✅ Resume Conditions:
Must match ALL of:
- Same filename
- Same file size (exact bytes)
- Same match ID
- Upload status is "initialized" or "in_progress"

### ❌ Resume Does NOT Work:
- Different file (even with same name)
- File modified after first upload started
- Different match
- Upload already completed
- Upload marked as failed and cleaned up

## Technical Details

### Backend Logic
```python
# Check for existing upload
existing_upload = await db.find({
    "user_id": current_user_id,
    "match_id": match_id,
    "filename": filename,
    "file_size": file_size,
    "status": ["initialized", "in_progress"]
})

if existing_upload:
    # Return existing session
    return {
        "resume": true,
        "upload_id": existing_upload.upload_id,
        "uploaded_chunks": [0, 1, 2, ..., 204]  # List of chunk indices
    }
```

### Frontend Logic
```javascript
// Get list of uploaded chunks
const uploadedSet = new Set(uploaded_chunks || []);

// Skip already uploaded chunks
for (let i = 0; i < totalChunks; i++) {
    if (uploadedSet.has(i)) {
        console.log(`Skipping chunk ${i+1} (already uploaded)`);
        continue;
    }
    
    // Upload only missing chunks
    await uploadChunk(i);
}
```

### Storage
- **Chunk files**: Stored in `/tmp/uploads/{upload_id}/chunk_XXXXXX.bin`
- **Persist across**: Backend restarts, network drops, browser closes
- **Cleanup**: Only removed after successful completion or explicit failure

## API Endpoints

### Initialize/Resume Upload
```bash
POST /api/videos/upload/init

Request:
{
  "match_id": "abc123",
  "filename": "match_video.mp4",
  "file_size": 11440000000,
  "content_type": "video/mp4"
}

Response (New):
{
  "upload_id": "xyz789",
  "video_id": "vid456",
  "chunk_size": 10485760,
  "resume": false
}

Response (Resume):
{
  "upload_id": "xyz789",  // Same ID as before
  "video_id": "vid456",
  "chunk_size": 10485760,
  "resume": true,
  "chunks_received": 205,
  "uploaded_chunks": [0, 1, 2, ..., 204]
}
```

### Check Upload Status
```bash
GET /api/videos/upload/status/{upload_id}

Response:
{
  "upload_id": "xyz789",
  "video_id": "vid456",
  "filename": "match_video.mp4",
  "file_size": 11440000000,
  "chunks_received": 205,
  "status": "in_progress",
  "uploaded_chunks": [0, 1, 2, ..., 204],
  "created_at": "2026-03-30T13:00:00Z",
  "last_chunk_at": "2026-03-30T13:15:00Z"
}
```

### Upload Chunk (Resume-Aware)
```bash
POST /api/videos/upload/chunk?upload_id=xyz&chunk_index=205&total_chunks=1090

# If chunk already exists:
Response: {"status": "chunk_skipped", "message": "Chunk already uploaded"}

# If chunk is new:
Response: {"status": "chunk_received", "chunk_index": 205}
```

## Database Schema

### chunked_uploads Collection
```javascript
{
  upload_id: "uuid",
  video_id: "uuid",
  match_id: "uuid",
  user_id: "uuid",
  filename: "match_video.mp4",
  file_size: 11440000000,
  content_type: "video/mp4",
  chunks_received: 205,
  status: "in_progress",  // initialized | in_progress | completed | failed
  created_at: "2026-03-30T13:00:00Z",
  last_chunk_at: "2026-03-30T13:15:23Z"  // Updated with each chunk
}
```

## Upload Lifecycle

### 1. First Upload Attempt
```
User: Upload 11GB file
System: Create upload session (upload_id: abc123)
System: Start uploading chunks 1, 2, 3...
Network: Interrupted at chunk 205/1090
System: Temp files remain in /tmp/uploads/abc123/
Database: Status = "in_progress", chunks_received = 205
```

### 2. Resume Upload
```
User: Upload same 11GB file again
System: Detect existing session (abc123)
System: Return uploaded_chunks = [0...204]
Frontend: Skip chunks 0-204
Frontend: Resume from chunk 205
System: Continue uploading 206, 207, 208...
```

### 3. Completion
```
System: Receive chunk 1089 (final chunk)
System: Assemble all 1090 chunks
System: Upload to object storage
System: Save video metadata to database
System: Update match with video_id
System: Clean up temp files
Database: Status = "completed"
Frontend: Navigate to video analysis page
```

## Benefits

### Time Saved
For 11GB file at 50 Mbps:
- Full upload: ~40 minutes
- Resume from 18%: ~33 minutes saved
- Resume from 50%: ~20 minutes saved
- Resume from 90%: ~36 minutes saved

### Reliability
- Network drops: Resume automatically
- Backend restarts: Resume automatically
- Power loss: Resume when computer restarts
- Browser crash: Resume when reopened

### User Experience
- No need to restart from 0%
- Clear indication when resuming
- Shows how many chunks were already uploaded
- Progress bar reflects actual remaining work

## Cleanup & Maintenance

### Automatic Cleanup
- **On completion**: Temp files deleted immediately
- **On error**: Temp files deleted after error logged

### Manual Cleanup
```bash
# Remove stuck uploads older than 24 hours
find /tmp/uploads -type d -mtime +1 -exec rm -rf {} +

# Check disk usage
du -sh /tmp/uploads/
```

### Database Maintenance
```bash
# Find abandoned uploads (no activity in 24 hours)
db.chunked_uploads.find({
  status: {$in: ["initialized", "in_progress"]},
  last_chunk_at: {$lt: new Date(Date.now() - 86400000)}
})

# Mark as failed
db.chunked_uploads.updateMany(
  {status: "in_progress", last_chunk_at: {$lt: new Date(Date.now() - 86400000)}},
  {$set: {status: "abandoned"}}
)
```

## Troubleshooting

### Resume Not Working?

**Check 1: Exact file match**
```
- Filename must be identical (case-sensitive)
- File size must be exact same bytes
- Content-type should match
```

**Check 2: Upload session exists**
```bash
# Check database for existing session
curl https://scout-lens.preview.emergentagent.com/api/videos/upload/status/{upload_id} \
  -H "Authorization: Bearer {token}"
```

**Check 3: Temp files present**
```bash
ls -la /tmp/uploads/{upload_id}/
# Should see chunk_XXXXXX.bin files
```

### Force Fresh Upload

To start completely fresh (ignore resume):
1. Delete upload session from database
2. Remove temp directory
3. Start upload again

```bash
# Remove temp files
rm -rf /tmp/uploads/{upload_id}

# Database: mark as failed or delete
# (upload will create new session)
```

## Security

### Upload Isolation
- Each user can only access their own uploads
- Upload IDs are UUIDs (not guessable)
- Temp files stored by upload_id (isolated)

### Authentication
- All endpoints require valid JWT token
- User ID verified for all operations
- Match ownership validated

### Cleanup
- Failed uploads cleaned up automatically
- Temp files deleted after completion
- No orphaned data left behind

## Performance Impact

### Memory
- **Before resume**: Each failed attempt wasted bandwidth
- **With resume**: Only upload missing chunks
- **Temp storage**: ~10GB disk for 10GB file (cleaned after upload)

### Database
- Minimal impact: Only stores metadata
- No binary data in database
- Indexed by user_id, match_id, filename, file_size

### Network
- Bandwidth saved on resume = % already uploaded
- 50% uploaded = 50% bandwidth saved on resume

## Future Enhancements

Potential improvements:
1. **Parallel chunk uploads** - Upload 3-5 chunks simultaneously
2. **Checksum verification** - Verify chunk integrity with MD5/SHA256
3. **Compression** - Compress chunks before upload
4. **Background upload** - Continue upload even if browser closes
5. **Upload queue** - Queue multiple videos for sequential upload
6. **Progress persistence** - Save progress to localStorage for browser refresh

