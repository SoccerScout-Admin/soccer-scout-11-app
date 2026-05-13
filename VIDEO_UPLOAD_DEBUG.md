# Video Upload "Not Found" Error - Troubleshooting Steps

## Error Message
"Large file upload failed. Not Found"

## Common Causes & Solutions

### 1. Session/Authentication Issue
**Cause:** Your login session may have expired while on the match detail page.

**Solution:**
```
1. Log out completely
2. Log back in
3. Navigate to the match
4. Try upload again
```

### 2. Match Not Found
**Cause:** The match you're trying to upload to doesn't exist or isn't owned by you.

**Solution:**
```
1. Go back to dashboard
2. Verify the match exists in your match list
3. Click on the match again
4. Try upload
```

**Diagnostic Command:**
```bash
# Check if match exists for your user
TOKEN="<your-token>"
MATCH_ID="<your-match-id>"

curl "https://scout-lens.preview.emergentagent.com/api/debug/match/$MATCH_ID" \
  -H "Authorization: Bearer $TOKEN"
```

### 3. Network/CORS Issue
**Cause:** Browser blocking the upload request.

**Solution:**
```
1. Check browser console (F12) for CORS errors
2. Try in different browser (Chrome, Firefox, Safari)
3. Disable browser extensions temporarily
4. Check if you're on HTTPS (not HTTP)
```

### 4. Backend Not Responding
**Cause:** Backend service may have restarted or crashed.

**Solution:**
```bash
# Check backend status
sudo supervisorctl status backend

# If not running, start it
sudo supervisorctl start backend

# Check logs for errors
tail -50 /var/log/supervisor/backend.err.log
```

## Step-by-Step Debugging

### Step 1: Verify You're Logged In
```
1. Open browser DevTools (F12)
2. Go to Console tab
3. Type: localStorage.getItem('token')
4. Should show a long string
5. If null, log in again
```

### Step 2: Verify Match Exists
```
1. In DevTools Console, type:
   localStorage.getItem('user')
2. Note your user ID
3. Go to Dashboard
4. Confirm match appears in your list
```

### Step 3: Check Browser Console During Upload
```
1. Open DevTools (F12)
2. Go to Console tab
3. Start upload
4. Watch for messages:
   - "Starting chunked upload for file: ..."
   - "Initialized upload: ..."
   - "Uploading chunk 1/..."
   
5. If you see error, note the exact message
```

### Step 4: Check Network Tab
```
1. Open DevTools (F12)
2. Go to Network tab
3. Start upload
4. Find request to "/videos/upload/init"
5. Click on it
6. Check:
   - Status code (should be 200)
   - Response tab (shows error details)
   - Headers tab (verify Authorization header exists)
```

## Testing with Small File First

Before uploading 10GB+, test with small file:

```
1. Find or create a small video (< 100MB)
2. Try uploading it
3. If small file works but large doesn't:
   - Issue is with chunked upload implementation
   - Check backend logs
   - Verify chunk endpoints are working
```

## Backend Endpoint Testing

Test endpoints manually:

```bash
# 1. Login
TOKEN=$(curl -s -X POST "https://scout-lens.preview.emergentagent.com/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"your@email.com","password":"yourpassword"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin).get('token', ''))")

# 2. Get matches
curl -s "https://scout-lens.preview.emergentagent.com/api/matches" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 3. Copy a match ID from above, then test init
MATCH_ID="<paste-match-id-here>"
curl -s -X POST "https://scout-lens.preview.emergentagent.com/api/videos/upload/init" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"match_id\":\"$MATCH_ID\",\"filename\":\"test.mp4\",\"file_size\":1000000000,\"content_type\":\"video/mp4\"}" | \
  python3 -m json.tool
```

**Expected Responses:**
- **Login:** Should return `{"token": "...", "user": {...}}`
- **Matches:** Should return array of matches
- **Init:** Should return `{"upload_id": "...", "video_id": "...", "chunk_size": 10485760}`

## Specific Error Messages

### "Match not found"
- You're trying to upload to a match that doesn't exist
- Or the match belongs to another user
- Solution: Create new match or use existing match from your dashboard

### "Session expired"  
- Your login token expired (7 days)
- Solution: Log out and log back in

### "Network error"
- Connection lost during upload
- Backend unreachable
- CORS blocking request
- Solution: Check internet, verify backend is running

### "404 Not Found" (during init)
- Match ID is wrong or match doesn't exist
- Solution: Refresh page, select match again

### "422 Unprocessable Entity"
- Request body is malformed
- Required fields missing
- Solution: This shouldn't happen from UI, check browser console

## Still Not Working?

### Collect This Information:

1. **Browser Console Logs:**
   ```
   - Open DevTools (F12)
   - Console tab
   - Copy all red error messages
   ```

2. **Network Request Details:**
   ```
   - Open DevTools (F12)
   - Network tab
   - Find failed request
   - Right-click → Copy → Copy as cURL
   ```

3. **Backend Logs:**
   ```bash
   # Last 100 lines
   tail -100 /var/log/supervisor/backend.out.log > backend_logs.txt
   
   # Any errors
   grep -i error /var/log/supervisor/backend.err.log > backend_errors.txt
   ```

4. **Your Setup:**
   - Browser: Chrome/Firefox/Safari + version
   - File size: XX GB
   - File format: MP4/MOV/etc
   - When error occurs: Immediately / After some chunks / Other

## Workaround: Use Smaller File

While debugging, if you need to test other features:

1. **Compress your video:**
   ```
   # Using ffmpeg (if available)
   ffmpeg -i large_video.mp4 -vcodec h264 -crf 28 compressed_video.mp4
   ```

2. **Use first 10 minutes:**
   ```
   ffmpeg -i large_video.mp4 -t 600 -c copy first_10min.mp4
   ```

3. **Reduce resolution:**
   ```
   ffmpeg -i 4k_video.mp4 -vf scale=1920:1080 1080p_video.mp4
   ```

## Quick Fix Checklist

- [ ] Logged out and logged back in
- [ ] Confirmed match exists in dashboard
- [ ] Checked browser console for errors
- [ ] Tried different browser
- [ ] Tested with small file (< 100MB) first
- [ ] Verified backend is running
- [ ] Checked network tab in DevTools
- [ ] Tried creating new match and uploading there

## Contact Support With:

1. Exact error message from browser
2. Browser console logs
3. Network request details (from DevTools)
4. File size and format
5. When the error occurs (immediately, after X chunks, etc.)
6. Backend logs (if accessible)

