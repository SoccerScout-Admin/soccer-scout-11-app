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

  const handleChunkedUpload = async (file) => {
    setUploading(true);
    
    try {
      console.log(`Starting chunked upload for file: ${file.name} (${(file.size / (1024*1024*1024)).toFixed(2)}GB)`);
      
      // Initialize chunked upload (will resume if possible)
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
      
      // Create Set for fast lookup of already uploaded chunks
      const uploadedSet = new Set(uploaded_chunks || []);

      if (resume && uploaded_chunks && uploaded_chunks.length > 0) {
        const resumePercent = Math.round((uploaded_chunks.length / totalChunks) * 100);
        console.log(`🔄 RESUMING upload from chunk ${uploaded_chunks.length + 1}/${totalChunks} (${resumePercent}% complete)`);
        alert(`Resuming previous upload from ${resumePercent}%. ${uploaded_chunks.length} of ${totalChunks} chunks already uploaded.`);
      } else {
        console.log(`📤 Starting NEW upload: ${upload_id}, ${totalChunks} chunks of ${(chunk_size/(1024*1024)).toFixed(1)}MB each`);
      }

      // Upload chunks (skip already uploaded ones)
      let chunksUploaded = uploaded_chunks ? uploaded_chunks.length : 0;
      
      for (let i = 0; i < totalChunks; i++) {
        // Skip if chunk already uploaded
        if (uploadedSet.has(i)) {
          const progress = Math.round(((i + 1) / totalChunks) * 100);
          setUploadProgress(progress);
          console.log(`⏭️  Skipping chunk ${i + 1}/${totalChunks} (already uploaded)`);
          continue;
        }

        const start = i * chunk_size;
        const end = Math.min(start + chunk_size, file.size);
        const chunk = file.slice(start, end);

        const chunkFormData = new FormData();
        chunkFormData.append('file', chunk);

        console.log(`⬆️  Uploading chunk ${i + 1}/${totalChunks}...`);
        
        const chunkResponse = await axios.post(
          `${API}/videos/upload/chunk?upload_id=${upload_id}&chunk_index=${i}&total_chunks=${totalChunks}`,
          chunkFormData,
          {
            headers: getAuthHeader(),
            timeout: 120000
          }
        );

        chunksUploaded++;
        const progress = Math.round((chunksUploaded / totalChunks) * 100);
        setUploadProgress(progress);
        
        if (chunkResponse.data.status === 'chunk_skipped') {
          console.log(`⏭️  Chunk ${i + 1}/${totalChunks} was already uploaded (${progress}%)`);
        } else {
          console.log(`✓ Chunk ${i + 1}/${totalChunks} uploaded (${progress}%)`);
        }
        
        // Check if upload completed
        if (chunkResponse.data.status === 'completed') {
          console.log('✅ All chunks uploaded and assembled successfully!');
          break;
        }
      }

      console.log('Upload complete, navigating to video page...');
      navigate(`/video/${video_id}`);
    } catch (err) {
      console.error('Chunked upload failed:', err);
      console.error('Error details:', err.response?.data);
      
      let errorMessage = 'Large file upload failed. ';
      
      if (err.response) {
        const detail = err.response.data?.detail;
        const status = err.response.status;
        
        if (status === 404) {
          errorMessage += 'Match not found. Please refresh the page and try again.';
        } else if (status === 401) {
          errorMessage += 'Session expired. Please log in again.';
        } else if (detail) {
          errorMessage += detail;
        } else {
          errorMessage += `Error ${status}`;
        }
        
        // For network errors during upload, suggest resume
        if (status >= 500 || !status) {
          errorMessage += '\n\nYou can try uploading again - the system will resume from where it stopped.';
        }
      } else if (err.request) {
        errorMessage += 'Network error. You can try again and it will resume from where it stopped.';
      } else {
        errorMessage += err.message || 'Unknown error occurred.';
      }
      
      alert(errorMessage);
    } finally {
      setUploading(false);
      setUploadProgress(0);
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
                  <div className="bg-[#0A0A0A] h-2 mb-2">
                    <div className="bg-[#007AFF] h-2 transition-all" style={{ width: `${uploadProgress}%` }}></div>
                  </div>
                  <p className="text-sm text-[#A3A3A3]">Uploading... {uploadProgress}%</p>
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
