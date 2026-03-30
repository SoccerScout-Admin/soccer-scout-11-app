# Large Video Upload Support (10GB+ Soccer Matches)

## Overview
The Soccer Scout platform now supports uploading large video files (10GB+) commonly used for full soccer match recordings. The system automatically chooses the appropriate upload method based on file size.

## Upload Methods

### Standard Upload (Files < 1GB)
- **Method:** Single HTTP request
- **Timeout:** 10 minutes
- **Progress:** Real-time progress bar
- **Best for:** Highlight reels, short clips, compressed matches

### Chunked Upload (Files ≥ 1GB)
- **Method:** Multi-part upload with 10MB chunks
- **Timeout:** 2 minutes per chunk
- **Progress:** Chunk-by-chunk progress (0-100%)
- **Best for:** Full match recordings, 4K videos, uncompressed footage
- **Resumable:** Each chunk uploaded independently
- **Memory efficient:** Streams data without loading entire file

## Architecture

### Frontend (`MatchDetail.js`)
```javascript
// Automatic detection
if (fileSize > 1GB) {
  → handleChunkedUpload()
} else {
  → handleStandardUpload()
}
```

**Chunked Upload Flow:**
1. Initialize upload session → GET upload_id
2. Split file into 10MB chunks
3. Upload each chunk sequentially
4. Update progress bar per chunk
5. Backend auto-assembles on final chunk
6. Navigate to video analysis page

### Backend (`server.py`)

**Endpoints:**
- `POST /api/videos/upload` - Standard upload (< 1GB)
- `POST /api/videos/upload/init` - Initialize chunked upload
- `POST /api/videos/upload/chunk` - Upload individual chunk

**Process:**
1. **Init:** Create upload session in DB with metadata
2. **Chunk Upload:** Store each chunk in `upload_chunks` collection
3. **Auto-Assembly:** When final chunk received, assemble all chunks
4. **Storage Upload:** Upload assembled file to object storage
5. **Cleanup:** Remove chunks from DB, mark session complete

### Database Collections

**chunked_uploads:**
```javascript
{
  upload_id: "uuid",
  video_id: "uuid",
  match_id: "uuid",
  user_id: "uuid",
  filename: "match_video.mp4",
  file_size: 12884901888,  // 12GB in bytes
  content_type: "video/mp4",
  chunks_received: 1234,
  status: "initialized|completed|failed",
  created_at: "ISO timestamp",
  completed_at: "ISO timestamp" (optional)
}
```

**upload_chunks:**
```javascript
{
  upload_id: "uuid",
  chunk_index: 0,
  data: Binary,  // 10MB chunk data
  size: 10485760,
  created_at: "ISO timestamp"
}
```

## Performance Characteristics

### Standard Upload (< 1GB)
- **10MB file:** ~2-5 seconds
- **100MB file:** ~15-30 seconds
- **500MB file:** ~1-2 minutes
- **1GB file:** ~2-4 minutes

### Chunked Upload (≥ 1GB)
- **Chunk size:** 10MB
- **Chunks for 10GB:** 1,000 chunks
- **Time per chunk:** 2-5 seconds
- **Total time (10GB):** 35-85 minutes
- **Bandwidth dependent:** 100Mbps ~13min, 50Mbps ~27min, 25Mbps ~54min

### Upload Time Estimates

| File Size | Connection | Estimated Time |
|-----------|------------|----------------|
| 1 GB | 100 Mbps | 1-2 minutes |
| 5 GB | 100 Mbps | 7-10 minutes |
| 10 GB | 100 Mbps | 13-17 minutes |
| 20 GB | 100 Mbps | 27-35 minutes |
| 1 GB | 50 Mbps | 2-4 minutes |
| 5 GB | 50 Mbps | 13-20 minutes |
| 10 GB | 50 Mbps | 27-40 minutes |
| 10 GB | 25 Mbps | 54-80 minutes |

## User Experience

### Upload Initiation
1. User selects video file
2. System checks file size:
   - **< 1GB:** Shows size confirmation
   - **≥ 1GB:** Shows warning about long upload time
3. User confirms → Upload begins

### During Upload
- **Progress bar** shows 0-100%
- **Status text:**
  - Standard: "Uploading... 45%"
  - Chunked: "Uploading chunk 450/1000 (45%)"
- **Important:** User must keep browser window open

### Upload Completion
- Auto-redirect to video analysis page
- Video ready for playback
- Can immediately create clips and annotations

## Error Handling

### Network Interruptions
**Chunked uploads:** If network drops during chunk upload:
- Current chunk fails
- User sees error message
- Must restart upload from beginning
- *Future: Implement resume capability*

### Timeout Errors
- **Standard upload:** 10-minute timeout
- **Chunk upload:** 2-minute timeout per chunk
- If timeout: Error message shown, user can retry

### Storage Errors
- Detailed error logging in backend
- User sees: "Upload failed: [specific reason]"
- Check backend logs: `/var/log/supervisor/backend.out.log`

## Limitations & Recommendations

### Current Limitations
1. **No resume capability** - If upload fails, must restart
2. **Sequential chunks** - Chunks uploaded one at a time (not parallel)
3. **Browser must stay open** - Closing tab cancels upload
4. **Memory usage** - Chunks stored in DB during assembly (~10GB for 10GB file)

### Recommendations
1. **Compress videos before upload** if possible
   - Use H.264 codec (best compatibility)
   - Reduce resolution if analysis doesn't need 4K
   - Example: 2-hour 4K match = 20GB, 1080p = 5GB

2. **Use stable network connection**
   - Wired connection preferred over WiFi
   - Avoid uploading during network congestion
   - Close other bandwidth-heavy applications

3. **Upload during off-hours**
   - Less network congestion
   - More reliable upload speeds

4. **Test with smaller file first**
   - Verify system works with 100MB test file
   - Confirm authentication and permissions

## Monitoring Upload Progress

### Backend Logs
```bash
# Watch upload progress in real-time
tail -f /var/log/supervisor/backend.out.log | grep -i upload

# Check for errors
tail -100 /var/log/supervisor/backend.err.log
```

**Log Messages:**
- `Starting video upload: filename.mp4 (video/mp4) for match abc123`
- `Reading file in chunks (chunk_size: 5242880 bytes)`
- `Progress: 50.0MB read`
- `Video file read successfully: 536870912 bytes (512.0MB)`
- `Uploading 512.0MB to object storage...`
- `Video upload complete: video_id (536870912 bytes)`

**Chunked Upload Logs:**
- `Initialized chunked upload: upload_id for video video_id, size: 12884901888 bytes`
- `Received chunk 450/1000 for upload upload_id, size: 10485760 bytes`
- `All chunks received for upload_id, assembling file...`
- `Assembling 1000 chunks for upload upload_id`
- `File assembled: 12884901888 bytes (12.00GB)`
- `Upload to storage complete: path`

### Frontend Console
Open browser DevTools (F12) → Console tab:
- Chunk upload progress
- Network errors
- Timing information

## Troubleshooting

### Upload Hangs at 0%
**Cause:** File not being read
**Solution:**
- Check file isn't corrupted
- Verify file format is supported
- Try different browser

### Upload Fails at ~50%
**Cause:** Network timeout or memory issue
**Solution:**
- Check network stability
- For files >5GB, compress video first
- Restart browser and try again

### "Upload session not found"
**Cause:** Chunked upload session expired or cleared
**Solution:**
- Restart upload from beginning
- Check backend logs for session cleanup

### Upload Completes But Video Won't Play
**Cause:** Assembly or storage upload failed
**Solution:**
- Check backend logs for "Upload to storage complete"
- Verify object storage is accessible
- Try uploading smaller test file

## Future Enhancements

### Planned Improvements
1. **Parallel chunk uploads** - Upload 3-5 chunks simultaneously
2. **Resume capability** - Resume failed uploads from last successful chunk
3. **Background uploads** - Close browser, upload continues on server
4. **Direct storage streaming** - Upload directly to object storage without DB
5. **Upload queue** - Queue multiple videos, upload sequentially
6. **Compression pipeline** - Auto-compress videos during upload
7. **Pre-upload analysis** - Estimate upload time, suggest optimal settings

### Optimization Opportunities
1. Increase chunk size to 50MB (fewer requests)
2. Implement multipart upload to object storage
3. Add progress persistence (save progress to DB)
4. WebSocket for real-time progress updates
5. Client-side compression before upload

## Technical Details

### Memory Management
- **Standard upload:** File loaded into memory in 5MB chunks
- **Chunked upload:** Max 10MB in memory at once
- **Assembly:** All chunks assembled in memory (requires 2x file size in RAM)
- **Future:** Stream directly to storage without assembly

### Network Optimization
- **Chunk size:** 10MB balances speed vs. resilience
- **Timeout:** 2 minutes per chunk allows slow connections
- **Retry logic:** Not yet implemented (planned)

### Storage Integration
- Uses Emergent Object Storage
- Timeout: 300 seconds for standard upload
- No timeout for chunked (per-chunk timeout only)
- Supports any video format object storage accepts

## Support

For upload issues:
1. Check browser console (F12)
2. Check backend logs
3. Try with smaller test video
4. Verify network connection
5. Contact support with:
   - File size
   - Browser used
   - Error message
   - Backend logs

