# Video Upload Troubleshooting Guide

## Common Upload Issues and Solutions

### Issue 1: Upload Hangs or Times Out
**Symptoms:** Progress bar stops, browser shows "pending", no error message

**Causes:**
- Large video file (>100MB)
- Slow internet connection
- Server timeout (default 60s)

**Solutions:**
1. Frontend now has 5-minute timeout (300 seconds)
2. Try with smaller video file first (<50MB)
3. Check browser console for specific errors (F12)

---

### Issue 2: "Network Error" Message
**Symptoms:** Alert shows "Network error. Please check your connection"

**Causes:**
- Lost internet connection
- CORS issues
- Backend server down

**Solutions:**
1. Check if you can access the app (refresh page)
2. Check browser console for CORS errors
3. Verify backend is running: `sudo supervisorctl status backend`

---

### Issue 3: "Upload Failed: 400/404" Errors
**Symptoms:** Alert shows HTTP error code

**Causes:**
- Match ID not found (404)
- Invalid request format (400)
- Authentication token expired

**Solutions:**
1. Try logging out and logging back in
2. Create a new match and try uploading there
3. Check that you're on the correct match detail page

---

### Issue 4: Upload Succeeds But Video Won't Play
**Symptoms:** Upload completes, redirected to video page, but video doesn't load

**Causes:**
- Invalid video format
- Corrupted file
- Storage retrieval issue

**Solutions:**
1. Use common formats: MP4, MOV, AVI, WebM
2. Try a different video file
3. Check backend logs: `tail -50 /var/log/supervisor/backend.out.log`

---

## Testing Video Upload

### Via UI (Recommended):
1. Login to the app
2. Create a new match (or select existing)
3. Click "Select Video File" button
4. Choose a small video (<20MB for testing)
5. Watch progress bar - should show 0-100%
6. Should redirect to video analysis page automatically

### Via Command Line (Debug):
```bash
# 1. Login and get token
TOKEN=$(curl -s -X POST "https://scout-lens.preview.emergentagent.com/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"testcoach@demo.com","password":"password123"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin).get('token', ''))")

# 2. Get match ID
MATCHES=$(curl -s "https://scout-lens.preview.emergentagent.com/api/matches" \
  -H "Authorization: Bearer $TOKEN")
echo "$MATCHES"

# 3. Upload test video
MATCH_ID="<your-match-id>"
curl -X POST "https://scout-lens.preview.emergentagent.com/api/videos/upload?match_id=$MATCH_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/your/video.mp4"
```

---

## What to Check If Upload Fails

### 1. Check Browser Console (F12)
Look for:
- Red error messages
- Network tab - find the upload request, check response
- Console tab - look for JavaScript errors

### 2. Check Backend Logs
```bash
# Check recent errors
tail -50 /var/log/supervisor/backend.err.log

# Check upload attempts
tail -50 /var/log/supervisor/backend.out.log | grep -i upload

# Watch logs in real-time
tail -f /var/log/supervisor/backend.out.log
```

### 3. Check Authentication
```bash
# Verify token is valid
TOKEN=$(curl -s -X POST "https://scout-lens.preview.emergentagent.com/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"your-email","password":"your-password"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin).get('token', ''))")

# Test auth
curl "https://scout-lens.preview.emergentagent.com/api/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

### 4. Check Match Exists
```bash
# List your matches
curl "https://scout-lens.preview.emergentagent.com/api/matches" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Improvements Made

### Backend (`/app/backend/server.py`):
- ✅ Added detailed logging for upload process
- ✅ Added try-catch for better error messages
- ✅ Log file size, filename, match_id
- ✅ Log storage upload success/failure

### Frontend (`/app/frontend/src/pages/MatchDetail.js`):
- ✅ Added file type validation (must be video/*)
- ✅ Added file size warning (>500MB)
- ✅ Increased timeout to 5 minutes (was default 60s)
- ✅ Removed explicit Content-Type header (axios handles it)
- ✅ Better error messages showing specific issue

---

## Video Format Support

### Recommended Formats:
- **MP4** (H.264 codec) - Best compatibility
- **WebM** - Good for web
- **MOV** - Apple devices
- **AVI** - Older format

### Not Recommended:
- FLV (Flash video)
- WMV (Windows Media)
- Proprietary codecs

---

## Size Limits

### Current Limits:
- **No hard limit set** - But practical limits exist:
  - Object storage timeout: ~5 minutes
  - Browser memory: Depends on device
  - Network speed: Upload time varies

### Recommendations:
- **For testing:** 10-50 MB
- **For demos:** 50-200 MB
- **For production:** 200-500 MB
- **Large files (>500MB):** Consider compression first

---

## Need More Help?

1. Check backend logs: `/var/log/supervisor/backend.out.log`
2. Check frontend logs: Browser DevTools Console (F12)
3. Try with a small test video first
4. Verify authentication is working (can you see matches?)
5. Check network tab in DevTools for exact error response

## Recent Improvements

With the latest updates, you should now see:
- ✅ File type validation message if wrong file selected
- ✅ Size warning for files >500MB
- ✅ Specific error messages (not just "upload failed")
- ✅ Detailed logs in backend for debugging
- ✅ 5-minute timeout for large files
