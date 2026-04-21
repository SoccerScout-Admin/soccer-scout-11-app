import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, UploadSimple, VideoCamera, Spinner } from '@phosphor-icons/react';

const MatchDetail = () => {
  const { matchId } = useParams();
  const navigate = useNavigate();
  const [match, setMatch] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('');

  useEffect(() => {
    fetchMatch();
  }, [matchId]);

  const fetchMatch = async () => {
    try {
      const response = await axios.get(`${API}/matches/${matchId}`, { headers: getAuthHeader() });
      setMatch(response.data);
    } catch (err) {
      console.error('Failed to fetch match:', err);
    }
  };

  const handleVideoUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // Validate file
    if (!file.type.startsWith('video/')) {
      alert('Please select a valid video file');
      return;
    }

    const fileSizeMB = file.size / (1024 * 1024);
    const fileSizeGB = file.size / (1024 * 1024 * 1024);

    // For files > 1GB, use chunked upload
    if (file.size > 1024 * 1024 * 1024) {
      alert(`Uploading large file (${fileSizeGB.toFixed(2)}GB). This may take several minutes. Please don't close this window.`);
      await handleChunkedUpload(file);
    } else {
      // Standard upload for files < 1GB
      if (fileSizeMB > 500) {
        const confirmUpload = window.confirm(
          `This video is ${Math.round(fileSizeMB)}MB. Continue upload?`
        );
        if (!confirmUpload) return;
      }
      await handleStandardUpload(file);
    }
  };

  const handleStandardUpload = async (file) => {
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(
        `${API}/videos/upload?match_id=${matchId}`,
        formData,
        {
          headers: {
            ...getAuthHeader()
          },
          onUploadProgress: (progressEvent) => {
            const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(progress);
          },
          timeout: 600000
        }
      );
      navigate(`/video/${response.data.video_id}`);
    } catch (err) {
      console.error('Upload failed:', err);
      let errorMessage = 'Video upload failed. ';
      
      if (err.response) {
        errorMessage += err.response.data?.detail || `Error: ${err.response.status}`;
      } else if (err.request) {
        errorMessage += 'Network error. Please check your connection.';
      } else {
        errorMessage += err.message || 'Unknown error occurred.';
      }
      
      alert(errorMessage);
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const uploadChunkWithRetry = async (url, formData, maxRetries = 3) => {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        const response = await axios.post(url, formData, {
          headers: getAuthHeader(),
          timeout: 300000, // 5 min per chunk
        });
        return response;
      } catch (err) {
        const isRetryable = !err.response || err.response.status >= 500 || err.code === 'ECONNABORTED';
        if (attempt === maxRetries || !isRetryable) throw err;
        const delay = Math.min(2000 * Math.pow(2, attempt - 1), 30000);
        console.warn(`Chunk upload failed (attempt ${attempt}/${maxRetries}), retrying in ${delay/1000}s...`, err.message);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  };

  const handleChunkedUpload = async (file) => {
    setUploading(true);
    setUploadStatus('Initializing upload...');
    
    try {
      const initResponse = await axios.post(
        `${API}/videos/upload/init`,
        {
          match_id: matchId,
          filename: file.name,
          file_size: file.size,
          content_type: file.type || 'video/mp4'
        },
        { headers: getAuthHeader(), timeout: 30000 }
      );

      const { upload_id, video_id, chunk_size, resume, uploaded_chunks } = initResponse.data;
      const totalChunks = Math.ceil(file.size / chunk_size);
      const uploadedSet = new Set(uploaded_chunks || []);

      // Build list of only the chunks that still need uploading
      const chunksToUpload = [];
      for (let i = 0; i < totalChunks; i++) {
        if (!uploadedSet.has(i)) chunksToUpload.push(i);
      }

      const alreadyDone = totalChunks - chunksToUpload.length;
      let uploadedCount = alreadyDone;

      if (resume && alreadyDone > 0) {
        const resumePercent = Math.round((alreadyDone / totalChunks) * 100);
        setUploadProgress(resumePercent);
        setUploadStatus(`Resuming: ${alreadyDone}/${totalChunks} chunks already saved (${resumePercent}%) — ${chunksToUpload.length} remaining`);
        console.log(`RESUMING from ${resumePercent}% — ${alreadyDone}/${totalChunks} done, ${chunksToUpload.length} remaining`);
      } else {
        setUploadProgress(0);
        setUploadStatus(`Starting upload: ${totalChunks} chunks`);
      }

      for (const i of chunksToUpload) {
        const start = i * chunk_size;
        const end = Math.min(start + chunk_size, file.size);
        const chunk = file.slice(start, end);

        const chunkFormData = new FormData();
        chunkFormData.append('file', chunk);

        const chunkResponse = await uploadChunkWithRetry(
          `${API}/videos/upload/chunk?upload_id=${upload_id}&chunk_index=${i}&total_chunks=${totalChunks}`,
          chunkFormData
        );

        uploadedCount++;
        const progress = Math.round((uploadedCount / totalChunks) * 100);
        setUploadProgress(progress);
        setUploadStatus(`Uploading: ${uploadedCount}/${totalChunks} chunks (${progress}%)`);

        if (chunkResponse.data.status === 'completed') {
          setUploadStatus('Upload complete! Starting AI processing...');
          break;
        }
      }

      navigate(`/video/${video_id}`);
    } catch (err) {
      console.error('Chunked upload failed:', err);
      
      let errorMessage = 'Upload interrupted. ';
      if (err.response) {
        const detail = err.response.data?.detail;
        if (detail) errorMessage += detail;
        else errorMessage += `Error ${err.response.status}`;
      } else if (err.request) {
        errorMessage += 'Network error.';
      } else {
        errorMessage += err.message || 'Unknown error.';
      }
      errorMessage += '\n\nTry again — it will resume from where it stopped.';
      alert(errorMessage);
    } finally {
      setUploading(false);
      setUploadProgress(0);
      setUploadStatus('');
    }
  };

  if (!match) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <Spinner size={48} className="text-[#007AFF] animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center gap-4">
          <button
            data-testid="back-to-dashboard-btn"
            onClick={() => navigate('/')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10"
          >
            <ArrowLeft size={24} className="text-white" />
          </button>
          <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Match Details</h1>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="bg-[#141414] border border-white/10 p-8 mb-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider mb-2">{match.competition || 'Friendly'}</p>
              <h2 className="text-5xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                {match.team_home} vs {match.team_away}
              </h2>
              <p className="text-[#A3A3A3]">{new Date(match.date).toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</p>
            </div>
          </div>

          {!match.video_id ? (
            <div className="border-2 border-dashed border-white/10 p-12 text-center">
              <VideoCamera size={64} className="text-[#A3A3A3] mx-auto mb-4" />
              <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Upload Match Video</h3>
              <p className="text-[#A3A3A3] mb-6">Upload the match footage to enable AI analysis and annotations</p>
              
              {uploading ? (
                <div className="max-w-md mx-auto">
                  <div className="bg-[#0A0A0A] h-3 mb-3 rounded-full overflow-hidden">
                    <div className="bg-[#007AFF] h-3 rounded-full" style={{ width: `${uploadProgress}%`, transition: 'width 0.3s ease' }}></div>
                  </div>
                  <p className="text-sm text-white font-medium mb-1">{uploadProgress}%</p>
                  {uploadStatus && (
                    <p className="text-xs text-[#A3A3A3]" data-testid="upload-status-text">{uploadStatus}</p>
                  )}
                </div>
              ) : (
                <label
                  data-testid="upload-video-btn"
                  className="inline-flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors cursor-pointer"
                >
                  <UploadSimple size={24} weight="bold" />
                  Select Video File
                  <input
                    type="file"
                    accept="video/*"
                    onChange={handleVideoUpload}
                    className="hidden"
                  />
                </label>
              )}
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-2 text-[#39FF14] mb-4">
                <VideoCamera size={24} />
                <span className="font-bold tracking-wider uppercase">Video Uploaded</span>
              </div>
              <button
                data-testid="view-analysis-btn"
                onClick={() => navigate(`/video/${match.video_id}`)}
                className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors"
              >
                View Analysis
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default MatchDetail;
