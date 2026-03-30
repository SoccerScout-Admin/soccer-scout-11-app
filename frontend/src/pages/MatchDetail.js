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

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(
        `${API}/videos/upload?match_id=${matchId}`,
        formData,
        {
          headers: {
            ...getAuthHeader(),
            'Content-Type': 'multipart/form-data'
          },
          onUploadProgress: (progressEvent) => {
            const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(progress);
          }
        }
      );
      navigate(`/video/${response.data.video_id}`);
    } catch (err) {
      console.error('Upload failed:', err);
      alert('Video upload failed. Please try again.');
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
