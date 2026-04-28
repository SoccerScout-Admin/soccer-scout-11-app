import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';

const VideoAnalysis = () => {
  const { videoId } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const [videoMetadata, setVideoMetadata] = useState(null);
  const [match, setMatch] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [clips, setClips] = useState([]);
  const [players, setPlayers] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [analyzing, setAnalyzing] = useState(false);
  const [annotationMode, setAnnotationMode] = useState(null);
  const [annotationText, setAnnotationText] = useState('');
  const [selectedPlayerId, setSelectedPlayerId] = useState('');
  const [selectedClipPlayerIds, setSelectedClipPlayerIds] = useState([]);
  const [showAnnotationForm, setShowAnnotationForm] = useState(false);
  const [showClipForm, setShowClipForm] = useState(false);
  const [clipFormData, setClipFormData] = useState({ title: '', start_time: 0, end_time: 0, clip_type: 'highlight', description: '' });
  const [currentTimestamp, setCurrentTimestamp] = useState(0);
  const [videoDuration, setVideoDuration] = useState(0);
  const [markers, setMarkers] = useState([]);
  const [showTrimPanel, setShowTrimPanel] = useState(false);
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [downloadingClip, setDownloadingClip] = useState(null);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [serverBootId, setServerBootId] = useState(null);
  const [serverRestarted, setServerRestarted] = useState(false);

  const fetchProcessingStatus = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/videos/${videoId}/processing-status`, { headers: getAuthHeader() });
      const data = response.data;
      setProcessingStatus(data);

      // Detect server restart via boot_id change
      if (data.server_boot_id) {
        if (serverBootId && serverBootId !== data.server_boot_id) {
          console.log('Server restarted detected — boot_id changed');
          setServerRestarted(true);
          // If processing was in progress, server auto-resumes on startup
          // Refresh analyses to get any that completed before restart
          const res = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
          setAnalyses(res.data);
        }
        setServerBootId(data.server_boot_id);
      }

      return data;
    } catch (err) {
      console.error('Failed to fetch processing status:', err);
      return null;
    }
  }, [videoId, serverBootId]);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [metaRes, analysesRes, annotationsRes, clipsRes] = await Promise.all([
          axios.get(`${API}/videos/${videoId}/metadata`, { headers: getAuthHeader() }),
          axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() }),
          axios.get(`${API}/annotations/video/${videoId}`, { headers: getAuthHeader() }),
          axios.get(`${API}/clips/video/${videoId}`, { headers: getAuthHeader() })
        ]);
        setVideoMetadata(metaRes.data);
        setAnalyses(analysesRes.data);
        setAnnotations(annotationsRes.data);
        setClips(clipsRes.data);

        if (metaRes.data.match_id) {
          const matchRes = await axios.get(`${API}/matches/${metaRes.data.match_id}`, { headers: getAuthHeader() });
          setMatch(matchRes.data);
          // Fetch players for this match
          try {
            const playersRes = await axios.get(`${API}/players/match/${metaRes.data.match_id}`, { headers: getAuthHeader() });
            setPlayers(playersRes.data);
          } catch (e) { console.error('Failed to fetch players:', e); }
        }
        // Fetch timeline markers
        try {
          const markersRes = await axios.get(`${API}/markers/video/${videoId}`, { headers: getAuthHeader() });
          setMarkers(markersRes.data);
        } catch (e) { console.error('Failed to fetch markers:', e); }
      } catch (err) {
        console.error('Failed to load data:', err);
      }
    };
    loadData();
    fetchProcessingStatus();
  }, [videoId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll processing status — always poll every 8s (acts as heartbeat + status check)
  useEffect(() => {
    const interval = setInterval(async () => {
      const status = await fetchProcessingStatus();
      // If processing just completed, refresh analyses
      if (status && processingStatus && 
          (processingStatus.processing_status === 'processing' || processingStatus.processing_status === 'queued') &&
          (status.processing_status === 'completed' || status.processing_status === 'failed')) {
        const res = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
        setAnalyses(res.data);
        // Also refresh markers after processing completes
        try {
          const mkRes = await axios.get(`${API}/markers/video/${videoId}`, { headers: getAuthHeader() });
          setMarkers(mkRes.data);
        } catch (e) { /* ignore */ }
      }
    }, 8000);
    return () => clearInterval(interval);
  }, [fetchProcessingStatus, processingStatus, videoId]);

  const handleReprocess = async () => {
    try {
      await axios.post(`${API}/videos/${videoId}/reprocess`, {}, { headers: getAuthHeader() });
      setProcessingStatus({ processing_status: 'queued', processing_progress: 0 });
    } catch (err) {
      console.error('Reprocess failed:', err);
    }
  };

  const handleGenerateAnalysis = async (type) => {
    setAnalyzing(true);
    try {
      const res = await axios.post(
        `${API}/analysis/generate`,
        { video_id: videoId, analysis_type: type },
        { headers: getAuthHeader(), timeout: 300000 }
      );
      const analysesRes = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
      setAnalyses(analysesRes.data);
    } catch (err) {
      console.error('Analysis failed:', err);
      const errMsg = err.response?.data?.detail || err.message || 'Analysis failed.';
      const isBudget = errMsg.toLowerCase().includes('budget') || errMsg.toLowerCase().includes('quota') || errMsg.toLowerCase().includes('balance') || errMsg.toLowerCase().includes('limit');
      if (isBudget) {
        alert('AI analysis budget limit reached. Please go to Profile > Universal Key > Add Balance to add more credits, or enable auto top-up.');
      } else {
        alert(errMsg);
      }
    } finally {
      setAnalyzing(false);
    }
  };

  const handleTrimmedAnalysis = async (type) => {
    setAnalyzing(true);
    try {
      await axios.post(
        `${API}/analysis/generate-trimmed`,
        { video_id: videoId, analysis_type: type, trim_start: trimStart || null, trim_end: trimEnd || null },
        { headers: getAuthHeader(), timeout: 600000 }
      );
      const analysesRes = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
      setAnalyses(analysesRes.data);
      setShowTrimPanel(false);
    } catch (err) {
      alert(err.response?.data?.detail || 'Trimmed analysis failed.');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDownloadClip = async (clipId, clipTitle) => {
    setDownloadingClip(clipId);
    try {
      const response = await axios.get(`${API}/clips/${clipId}/extract`, {
        headers: getAuthHeader(),
        responseType: 'blob',
        timeout: 600000
      });
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'video/mp4' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${clipTitle || 'clip'}.mp4`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert('Failed to download clip. ' + (err.response?.data?.detail || err.message));
    } finally {
      setDownloadingClip(null);
    }
  };

  const handleAddAnnotation = async () => {
    if (!annotationText.trim() || !annotationMode) return;
    try {
      const payload = {
        video_id: videoId, timestamp: currentTimestamp,
        annotation_type: annotationMode, content: annotationText
      };
      if (selectedPlayerId) payload.player_id = selectedPlayerId;
      await axios.post(`${API}/annotations`, payload, { headers: getAuthHeader() });
      setAnnotationText('');
      setSelectedPlayerId('');
      setShowAnnotationForm(false);
      setAnnotationMode(null);
      const res = await axios.get(`${API}/annotations/video/${videoId}`, { headers: getAuthHeader() });
      setAnnotations(res.data);
    } catch (err) {
      console.error('Failed to create annotation:', err);
    }
  };

  const handleDeleteAnnotation = async (id) => {
    try {
      await axios.delete(`${API}/annotations/${id}`, { headers: getAuthHeader() });
      setAnnotations(annotations.filter(a => a.id !== id));
    } catch (err) {
      console.error('Failed to delete annotation:', err);
    }
  };

  const handleCreateClip = async () => {
    if (!clipFormData.title.trim()) return alert('Please enter a clip title');
    if (clipFormData.start_time >= clipFormData.end_time) return alert('End time must be after start time');
    try {
      const payload = { video_id: videoId, ...clipFormData };
      if (selectedClipPlayerIds.length > 0) payload.player_ids = selectedClipPlayerIds;
      await axios.post(`${API}/clips`, payload, { headers: getAuthHeader() });
      setShowClipForm(false);
      setClipFormData({ title: '', start_time: 0, end_time: 0, clip_type: 'highlight', description: '' });
      setSelectedClipPlayerIds([]);
      const res = await axios.get(`${API}/clips/video/${videoId}`, { headers: getAuthHeader() });
      setClips(res.data);
    } catch (err) {
      console.error('Failed to create clip:', err);
    }
  };

  const handleDeleteClip = async (id) => {
    try {
      await axios.delete(`${API}/clips/${id}`, { headers: getAuthHeader() });
      setClips(clips.filter(c => c.id !== id));
    } catch (err) {
      console.error('Failed to delete clip:', err);
    }
  };

  const seekTo = (time) => {
    if (videoRef.current) videoRef.current.currentTime = time;
  };

  const playClip = (clip) => {
    if (videoRef.current) {
      videoRef.current.currentTime = clip.start_time;
      videoRef.current.play();
      const handler = () => {
        if (videoRef.current && videoRef.current.currentTime >= clip.end_time) {
          videoRef.current.pause();
          videoRef.current.removeEventListener('timeupdate', handler);
        }
      };
      videoRef.current.addEventListener('timeupdate', handler);
    }
  };

  const handleDownloadHighlights = async () => {
    try {
      const response = await axios.get(`${API}/highlights/video/${videoId}`, { headers: getAuthHeader() });
      const blob = new Blob([JSON.stringify(response.data, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `highlights_${match?.team_home || ''}_vs_${match?.team_away || ''}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert('Failed to download highlights package');
    }
  };

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const getAnalysis = (type) => analyses.find(a => a.analysis_type === type);
  const isProcessing = processingStatus && (processingStatus.processing_status === 'processing' || processingStatus.processing_status === 'queued');
  const isProcessed = processingStatus && processingStatus.processing_status === 'completed';
  const processingFailed = processingStatus && processingStatus.processing_status === 'failed';

  const processingLabel = {
    'tactical': 'Tactical Analysis',
    'player_performance': 'Player Ratings',
    'highlights': 'Highlights Detection',
    'timeline_markers': 'Timeline Markers'
  };

  if (!videoMetadata) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-10 h-10 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" style={{ fontFamily: 'Inter, sans-serif' }}>
      {/* Header */}
      <header className="sticky top-0 z-50 bg-[#0A0A0A]/95 backdrop-blur-sm border-b border-white/5 px-6 py-3">
        <div className="max-w-[1400px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button data-testid="back-btn" onClick={() => navigate('/')}
              className="p-2 rounded-lg hover:bg-white/5 transition-colors">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
            </button>
            <div>
              <h1 className="text-lg font-semibold" style={{ fontFamily: 'Space Grotesk' }}>
                {match ? `${match.team_home} vs ${match.team_away}` : 'Video Analysis'}
              </h1>
              {match?.competition && <p className="text-xs text-[#888]">{match.competition} — {new Date(match.date + 'T00:00:00').toLocaleDateString()}</p>}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {isProcessed && (
              <button data-testid="download-package-btn" onClick={handleDownloadHighlights}
                className="flex items-center gap-2 px-4 py-2 rounded-full bg-[#1A3A1A] text-[#4ADE80] text-xs font-medium hover:bg-[#1A4A1A] transition-colors">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
                Download Package
              </button>
            )}
            <span className="text-xs text-[#666] bg-white/5 px-3 py-1.5 rounded-full">
              {(videoMetadata.size / (1024*1024*1024)).toFixed(2)} GB
            </span>
          </div>
        </div>
      </header>

      {/* Processing Banner */}
      {isProcessing && (
        <div data-testid="processing-banner" className="bg-gradient-to-r from-[#0C1A3D] to-[#0A0A0A] border-b border-[#1E3A6E]/30 px-6 py-4">
          <div className="max-w-[1400px] mx-auto">
            <div className="flex items-center gap-4">
              <div className="w-8 h-8 rounded-full bg-[#007AFF]/20 flex items-center justify-center flex-shrink-0">
                <div className="w-4 h-4 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-white">
                  {serverRestarted ? 'Server restarted — processing resumed automatically' : 'Processing your match video...'}
                </p>
                <p className="text-xs text-[#7AA2D4] mt-0.5">
                  {processingStatus.processing_current
                    ? `Running: ${processingLabel[processingStatus.processing_current] || processingStatus.processing_current}`
                    : 'Preparing video for AI analysis'}
                  {processingStatus.completed_types && processingStatus.completed_types.length > 0 && (
                    <span className="text-[#4ADE80] ml-2">
                      — {processingStatus.completed_types.length}/4 done
                    </span>
                  )}
                </p>
              </div>
              <div className="text-right">
                <p className="text-lg font-bold text-[#007AFF]">{processingStatus.processing_progress || 0}%</p>
              </div>
            </div>
            <div className="mt-3 h-1.5 bg-[#1A1A2E] rounded-full overflow-hidden">
              <div className="h-full bg-[#007AFF] rounded-full transition-all duration-500"
                style={{ width: `${processingStatus.processing_progress || 0}%` }} />
            </div>
            {/* Show completed types */}
            <div className="flex items-center gap-4 mt-3">
              {['tactical', 'player_performance', 'highlights', 'timeline_markers'].map(type => {
                const isDone = processingStatus.completed_types?.includes(type);
                const isCurrent = processingStatus.processing_current === type;
                const isFailed = processingStatus.failed_types?.includes(type);
                return (
                  <div key={type} className="flex items-center gap-1.5 text-[10px]">
                    {isDone ? (
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    ) : isCurrent ? (
                      <div className="w-3 h-3 border border-[#007AFF] border-t-transparent rounded-full animate-spin" />
                    ) : isFailed ? (
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
                    ) : (
                      <div className="w-3 h-3 rounded-full border border-[#333]" />
                    )}
                    <span className={isDone ? 'text-[#4ADE80]' : isCurrent ? 'text-[#007AFF]' : isFailed ? 'text-[#EF4444]' : 'text-[#555]'}>
                      {processingLabel[type]}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {processingFailed && (
        <div data-testid="processing-failed-banner" className="bg-[#1A0C0C] border-b border-[#6E1E1E]/30 px-6 py-4">
          <div className="max-w-[1400px] mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
              <div>
                <p className="text-sm text-[#EF4444]">Processing encountered an issue</p>
                <p className="text-xs text-[#888] mt-0.5">
                  {processingStatus.processing_error && (processingStatus.processing_error.toLowerCase().includes('budget') || processingStatus.processing_error.toLowerCase().includes('quota') || processingStatus.processing_error.toLowerCase().includes('balance'))
                    ? 'AI budget limit reached. Add balance in Profile > Universal Key to continue.'
                    : processingStatus.completed_types?.length > 0
                    ? `${processingStatus.completed_types.length}/4 analyses completed. ${processingStatus.failed_types?.length || 0} failed.`
                    : processingStatus.processing_error || 'Some analyses may not have completed'}
                </p>
              </div>
            </div>
            <button data-testid="retry-processing-btn" onClick={handleReprocess}
              className="px-4 py-2 rounded-full bg-[#EF4444]/10 text-[#EF4444] text-xs font-medium hover:bg-[#EF4444]/20 transition-colors">
              {processingStatus.completed_types?.length > 0 ? 'Resume Failed' : 'Retry Processing'}
            </button>
          </div>
        </div>
      )}

      <main className="max-w-[1400px] mx-auto px-6 py-6">
        {/* Data Integrity Warning */}
        {videoMetadata && videoMetadata.data_integrity && videoMetadata.data_integrity !== 'full' && (
          <div data-testid="data-integrity-warning" className="bg-[#1A1A0A] border border-[#FFB800]/30 rounded-lg px-6 py-4 mb-6">
            <div className="flex items-center gap-3">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FFB800" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <div>
                <p className="text-sm font-medium text-[#FFB800]">
                  {videoMetadata.data_integrity === 'unavailable' ? 'Video data unavailable' : 'Partial video data'}
                </p>
                <p className="text-xs text-[#888] mt-0.5">
                  {videoMetadata.data_integrity === 'unavailable'
                    ? 'All video chunks were lost during a server restart. Please re-upload the video.'
                    : `Only ${videoMetadata.chunks_available} of ${videoMetadata.chunks_total} chunks available (${Math.round(videoMetadata.chunks_available / videoMetadata.chunks_total * 100)}%). Video may stop playing early. Re-upload for full playback.`}
                </p>
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Video + Controls */}
          <div className="lg:col-span-8 space-y-4">
            <div className="bg-black rounded-lg overflow-hidden relative">
              <video ref={videoRef} data-testid="video-player" controls
                className="w-full aspect-video"
                src={`${API}/videos/${videoId}?token=${localStorage.getItem('token')}`}
                preload="auto"
                onTimeUpdate={(e) => setCurrentTimestamp(e.target.currentTime)}
                onLoadedMetadata={(e) => setVideoDuration(e.target.duration || 0)}
              />
              {/* AI Timeline Markers Bar */}
              {markers.length > 0 && videoDuration > 0 && (
                <div data-testid="timeline-markers-bar" className="absolute bottom-[52px] left-0 right-0 h-5 pointer-events-none z-10 px-[12px]">
                  {markers.map(m => {
                    const pct = (m.time / videoDuration) * 100;
                    if (pct < 0 || pct > 100) return null;
                    const colors = { goal: '#FFD700', shot: '#FF6B35', save: '#4ADE80', foul: '#EF4444', card: '#EF4444', substitution: '#A855F7', tactical: '#007AFF', chance: '#FFB800' };
                    const color = colors[m.type] || '#888';
                    return (
                      <button key={m.id} data-testid={`marker-${m.id}`}
                        title={`${formatTime(m.time)} — ${m.label}`}
                        onClick={() => seekTo(m.time)}
                        style={{ left: `${pct}%`, backgroundColor: color }}
                        className="absolute top-0 w-2.5 h-5 -translate-x-1/2 pointer-events-auto cursor-pointer hover:scale-y-125 transition-transform opacity-90 hover:opacity-100"
                      />
                    );
                  })}
                </div>
              )}
            </div>

            {/* Markers Legend */}
            {markers.length > 0 && (
              <div data-testid="markers-legend" className="flex items-center gap-3 flex-wrap bg-white/[0.03] rounded-lg px-3 py-2">
                <span className="text-[10px] text-[#666] uppercase tracking-wider">AI Markers:</span>
                {[['goal', '#FFD700', 'Goals'], ['shot', '#FF6B35', 'Shots'], ['save', '#4ADE80', 'Saves'], ['foul', '#EF4444', 'Fouls'], ['tactical', '#007AFF', 'Tactical'], ['chance', '#FFB800', 'Chances']].map(([type, color, label]) => {
                  const count = markers.filter(m => m.type === type).length;
                  if (count === 0) return null;
                  return (
                    <span key={type} className="flex items-center gap-1 text-[10px] text-[#AAA]">
                      <span className="w-2 h-2 rounded-sm inline-block" style={{ backgroundColor: color }} />
                      {label} ({count})
                    </span>
                  );
                })}
              </div>
            )}

            {/* Clip & Annotation Toolbar */}
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-1.5 bg-white/5 rounded-lg px-3 py-2">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#888" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                <span className="text-sm text-white font-mono">{formatTime(currentTimestamp)}</span>
              </div>
              <button data-testid="create-clip-btn"
                onClick={() => { setShowClipForm(true); setClipFormData({ ...clipFormData, start_time: currentTimestamp, end_time: currentTimestamp + 10 }); }}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#007AFF] text-white text-xs font-medium hover:bg-[#0066DD] transition-colors">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12"/></svg>
                Create Clip
              </button>
              {[['note', 'Note'], ['tactical', 'Tactical'], ['key_moment', 'Key Moment']].map(([mode, label]) => (
                <button key={mode} data-testid={`${mode}-tool-btn`}
                  onClick={() => { setAnnotationMode(mode); setShowAnnotationForm(true); }}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    annotationMode === mode ? 'bg-[#007AFF] text-white' : 'bg-white/5 text-[#888] hover:text-white hover:bg-white/10'
                  }`}>
                  {label}
                </button>
              ))}
              <div className="ml-auto">
                <button data-testid="trim-analyze-btn"
                  onClick={() => { setShowTrimPanel(!showTrimPanel); setTrimStart(0); setTrimEnd(Math.floor(videoDuration)); }}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    showTrimPanel ? 'bg-[#A855F7] text-white' : 'bg-white/5 text-[#888] hover:text-white hover:bg-white/10'
                  }`}>
                  Trim &amp; Analyze
                </button>
              </div>
            </div>

            {/* Trim Panel */}
            {showTrimPanel && (
              <div data-testid="trim-panel" className="bg-[#111] rounded-lg border border-[#A855F7]/30 p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold" style={{ fontFamily: 'Space Grotesk' }}>Analyze Video Section</h3>
                  <button data-testid="close-trim-panel" onClick={() => setShowTrimPanel(false)} className="text-[#666] hover:text-white">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                  </button>
                </div>
                <p className="text-xs text-[#888] mb-3">Select a time range to focus AI analysis on a specific section (e.g., first half, second half, a specific play).</p>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Start Time</label>
                    <div className="flex gap-2">
                      <input data-testid="trim-start-input" type="number" step="1" min="0" max={videoDuration}
                        value={trimStart} onChange={(e) => setTrimStart(Math.max(0, parseFloat(e.target.value) || 0))}
                        className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#A855F7] focus:outline-none" />
                      <button data-testid="trim-start-now-btn" onClick={() => setTrimStart(Math.floor(currentTimestamp))}
                        className="px-3 py-2 rounded-lg bg-white/10 text-[#A855F7] text-xs font-medium">Now</button>
                    </div>
                    <span className="text-[10px] text-[#555]">{formatTime(trimStart)}</span>
                  </div>
                  <div>
                    <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">End Time</label>
                    <div className="flex gap-2">
                      <input data-testid="trim-end-input" type="number" step="1" min="0" max={videoDuration}
                        value={trimEnd} onChange={(e) => setTrimEnd(Math.min(videoDuration, parseFloat(e.target.value) || 0))}
                        className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#A855F7] focus:outline-none" />
                      <button data-testid="trim-end-now-btn" onClick={() => setTrimEnd(Math.floor(currentTimestamp))}
                        className="px-3 py-2 rounded-lg bg-white/10 text-[#A855F7] text-xs font-medium">Now</button>
                    </div>
                    <span className="text-[10px] text-[#555]">{formatTime(trimEnd)}</span>
                  </div>
                </div>
                <p className="text-xs text-[#A855F7] mb-3">Duration: {formatTime(Math.max(0, trimEnd - trimStart))}</p>
                <div className="flex gap-2">
                  {['tactical', 'player_performance', 'highlights'].map(type => (
                    <button key={type} data-testid={`trim-analyze-${type}-btn`}
                      onClick={() => handleTrimmedAnalysis(type)} disabled={analyzing || trimStart >= trimEnd}
                      className="flex-1 px-3 py-2.5 rounded-lg bg-[#A855F7] hover:bg-[#9333EA] text-white text-xs font-medium transition-colors disabled:opacity-40">
                      {analyzing ? 'Analyzing...' : processingLabel[type] || type}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Clip Form */}
            {showClipForm && (
              <div className="bg-[#111] rounded-lg border border-white/10 p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold" style={{ fontFamily: 'Space Grotesk' }}>Create Clip</h3>
                  <button data-testid="close-clip-form-btn" onClick={() => setShowClipForm(false)} className="text-[#666] hover:text-white">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                  </button>
                </div>
                <div className="space-y-3">
                  <input data-testid="clip-title-input" type="text" placeholder="Clip title" value={clipFormData.title}
                    onChange={(e) => setClipFormData({ ...clipFormData, title: e.target.value })}
                    className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none" />
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Start</label>
                      <div className="flex gap-2">
                        <input data-testid="clip-start-time-input" type="number" step="0.1" value={clipFormData.start_time}
                          onChange={(e) => setClipFormData({ ...clipFormData, start_time: parseFloat(e.target.value) || 0 })}
                          className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none" />
                        <button data-testid="set-start-time-btn" onClick={() => setClipFormData({ ...clipFormData, start_time: currentTimestamp })}
                          className="px-3 py-2 rounded-lg bg-white/10 text-[#007AFF] text-xs font-medium hover:bg-white/15 transition-colors">Now</button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">End</label>
                      <div className="flex gap-2">
                        <input data-testid="clip-end-time-input" type="number" step="0.1" value={clipFormData.end_time}
                          onChange={(e) => setClipFormData({ ...clipFormData, end_time: parseFloat(e.target.value) || 0 })}
                          className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none" />
                        <button data-testid="set-end-time-btn" onClick={() => setClipFormData({ ...clipFormData, end_time: currentTimestamp })}
                          className="px-3 py-2 rounded-lg bg-white/10 text-[#007AFF] text-xs font-medium hover:bg-white/15 transition-colors">Now</button>
                      </div>
                    </div>
                  </div>
                  <select data-testid="clip-type-select" value={clipFormData.clip_type}
                    onChange={(e) => setClipFormData({ ...clipFormData, clip_type: e.target.value })}
                    className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none">
                    <option value="highlight">Highlight</option>
                    <option value="goal">Goal</option>
                    <option value="save">Save</option>
                    <option value="tactical">Tactical Play</option>
                    <option value="mistake">Mistake</option>
                  </select>
                  <textarea data-testid="clip-description-input" placeholder="Description (optional)" value={clipFormData.description}
                    onChange={(e) => setClipFormData({ ...clipFormData, description: e.target.value })}
                    className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none resize-none" rows="2" />
                  {players.length > 0 && (
                    <div>
                      <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Tag Players (optional)</label>
                      <div className="flex flex-wrap gap-1.5 bg-white/5 rounded-lg p-2 border border-white/10 max-h-24 overflow-y-auto">
                        {players.map(p => {
                          const isSelected = selectedClipPlayerIds.includes(p.id);
                          return (
                            <button key={p.id} type="button" data-testid={`clip-player-tag-${p.id}`}
                              onClick={() => setSelectedClipPlayerIds(
                                isSelected ? selectedClipPlayerIds.filter(id => id !== p.id) : [...selectedClipPlayerIds, p.id]
                              )}
                              className={`px-2 py-1 text-[10px] font-medium transition-colors ${
                                isSelected ? 'bg-[#007AFF] text-white' : 'bg-white/5 text-[#888] hover:text-white hover:bg-white/10'
                              }`}>
                              #{p.number || '?'} {p.name}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <button data-testid="save-clip-btn" onClick={handleCreateClip}
                    className="w-full bg-[#007AFF] hover:bg-[#0066DD] text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors">
                    Save Clip
                  </button>
                </div>
              </div>
            )}

            {/* Annotation Form */}
            {showAnnotationForm && (
              <div className="bg-[#111] rounded-lg border border-white/10 p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold" style={{ fontFamily: 'Space Grotesk' }}>
                    Add {annotationMode?.replace('_', ' ')} at {formatTime(currentTimestamp)}
                  </h3>
                  <button data-testid="close-annotation-form-btn"
                    onClick={() => { setShowAnnotationForm(false); setAnnotationMode(null); setAnnotationText(''); }}
                    className="text-[#666] hover:text-white">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                  </button>
                </div>
                <textarea data-testid="annotation-text-input" value={annotationText}
                  onChange={(e) => setAnnotationText(e.target.value)}
                  className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 mb-3 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none resize-none" rows="3"
                  placeholder="Enter your annotation..." />
                {players.length > 0 && (
                  <div className="mb-3">
                    <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Tag Player (optional)</label>
                    <select data-testid="annotation-player-select" value={selectedPlayerId}
                      onChange={(e) => setSelectedPlayerId(e.target.value)}
                      className="w-full bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none">
                      <option value="">No player</option>
                      {players.map(p => (
                        <option key={p.id} value={p.id}>#{p.number || '?'} {p.name} ({p.team})</option>
                      ))}
                    </select>
                  </div>
                )}
                <button data-testid="save-annotation-btn" onClick={handleAddAnnotation}
                  className="bg-[#007AFF] hover:bg-[#0066DD] text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
                  Save Annotation
                </button>
              </div>
            )}

            {/* Analysis Tabs */}
            <div className="bg-[#111] rounded-lg border border-white/10">
              <div className="flex border-b border-white/5">
                {[
                  ['overview', 'Overview'],
                  ['tactical', 'Tactical'],
                  ['player_performance', 'Players'],
                  ['highlights', 'Highlights'],
                  ['timeline', 'Timeline']
                ].map(([key, label]) => (
                  <button key={key} data-testid={`${key}-tab-btn`} onClick={() => setActiveTab(key)}
                    className={`px-5 py-3.5 text-xs font-semibold uppercase tracking-wider transition-colors relative ${
                      activeTab === key ? 'text-white' : 'text-[#666] hover:text-[#AAA]'
                    }`}>
                    {label}
                    {activeTab === key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#007AFF]" />}
                    {key !== 'overview' && key !== 'timeline' && getAnalysis(key) && getAnalysis(key).status === 'completed' && (
                      <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-[#4ADE80] inline-block" />
                    )}
                    {key === 'timeline' && markers.length > 0 && (
                      <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-[#FFD700] inline-block" />
                    )}
                  </button>
                ))}
              </div>

              <div className="p-6">
                {activeTab === 'overview' ? (
                  <div data-testid="overview-content">
                    <h3 className="text-base font-semibold mb-4" style={{ fontFamily: 'Space Grotesk' }}>Analysis Summary</h3>
                    {isProcessing ? (
                      <div className="text-center py-8">
                        <div className="w-10 h-10 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                        <p className="text-sm text-[#888]">Your video is being processed by AI...</p>
                        <p className="text-xs text-[#555] mt-1">Tactical analysis, player ratings, and highlights will appear here once ready.</p>
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {['tactical', 'player_performance', 'highlights'].map(type => {
                          const analysis = getAnalysis(type);
                          const labels = { tactical: 'Tactical Analysis', player_performance: 'Player Ratings', highlights: 'Highlights' };
                          const icons = {
                            tactical: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18M12 3v18"/></svg>,
                            player_performance: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>,
                            highlights: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                          };
                          return (
                            <div key={type} data-testid={`overview-${type}`}
                              className={`rounded-lg border p-4 cursor-pointer transition-colors ${
                                analysis && analysis.status === 'completed'
                                  ? 'border-[#4ADE80]/20 bg-[#0A1A0A] hover:bg-[#0A200A]'
                                  : analysis && analysis.status === 'failed'
                                  ? 'border-[#EF4444]/20 bg-[#1A0A0A]'
                                  : 'border-white/5 bg-white/[0.02] hover:bg-white/[0.04]'
                              }`}
                              onClick={() => setActiveTab(type)}>
                              <div className="flex items-center gap-3 mb-2">
                                <div className={`${analysis?.status === 'completed' ? 'text-[#4ADE80]' : 'text-[#555]'}`}>
                                  {icons[type]}
                                </div>
                                <span className="text-xs font-semibold uppercase tracking-wider text-[#888]">{labels[type]}</span>
                              </div>
                              {analysis?.status === 'completed' ? (
                                <p className="text-xs text-[#AAA] line-clamp-3">{analysis.content.substring(0, 150)}...</p>
                              ) : analysis?.status === 'failed' ? (
                                <p className="text-xs text-[#EF4444]">Failed — click to retry</p>
                              ) : (
                                <p className="text-xs text-[#555]">{isProcessing ? 'Processing...' : 'Not generated yet'}</p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {!isProcessing && !isProcessed && processingStatus?.processing_status !== 'queued' && (
                      <div className="mt-6 text-center">
                        <button data-testid="start-processing-btn" onClick={handleReprocess}
                          className="px-6 py-3 rounded-full bg-[#007AFF] text-white text-sm font-medium hover:bg-[#0066DD] transition-colors">
                          Start AI Processing
                        </button>
                        <p className="text-xs text-[#555] mt-2">Generates tactical analysis, player ratings, and highlights automatically</p>
                      </div>
                    )}
                  </div>
                ) : activeTab === 'timeline' ? (
                  <div data-testid="timeline-content">
                    <h3 className="text-base font-semibold mb-4" style={{ fontFamily: 'Space Grotesk' }}>AI Timeline Markers</h3>
                    {markers.length === 0 ? (
                      <div className="text-center py-12">
                        <p className="text-sm text-[#666] mb-2">No timeline markers yet.</p>
                        <p className="text-xs text-[#555]">Markers are automatically generated during AI processing.</p>
                      </div>
                    ) : (
                      <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
                        {markers.sort((a, b) => a.time - b.time).map(m => {
                          const colors = { goal: '#FFD700', shot: '#FF6B35', save: '#4ADE80', foul: '#EF4444', card: '#EF4444', substitution: '#A855F7', tactical: '#007AFF', chance: '#FFB800' };
                          const color = colors[m.type] || '#888';
                          return (
                            <div key={m.id} data-testid={`timeline-event-${m.id}`}
                              className="flex items-center gap-3 px-3 py-2 bg-white/[0.03] rounded hover:bg-white/[0.06] transition-colors cursor-pointer"
                              onClick={() => seekTo(m.time)}>
                              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: color }} />
                              <span className="text-xs font-mono text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded min-w-[50px] text-center">
                                {formatTime(m.time)}
                              </span>
                              <span className="text-[10px] text-[#666] uppercase w-16 flex-shrink-0">{m.type}</span>
                              <span className="text-xs text-[#CCC] flex-1">{m.label}</span>
                              <span className="text-[10px] text-[#555]">{m.team}</span>
                              <div className="flex gap-0.5">
                                {Array.from({ length: m.importance }, (_, i) => (
                                  <span key={i} className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ) : (
                  <div data-testid={`${activeTab}-content`}>
                    {(() => {
                      const analysis = getAnalysis(activeTab);
                      const labels = { tactical: 'Tactical Analysis', player_performance: 'Player Performance', highlights: 'Match Highlights' };
                      
                      if (analysis && analysis.status === 'completed') {
                        return (
                          <div>
                            <div className="flex items-center justify-between mb-4">
                              <h3 className="text-base font-semibold" style={{ fontFamily: 'Space Grotesk' }}>{labels[activeTab]}</h3>
                              <button data-testid="regenerate-analysis-btn" onClick={() => handleGenerateAnalysis(activeTab)} disabled={analyzing}
                                className="text-xs text-[#007AFF] hover:text-[#0066DD] font-medium disabled:opacity-50">
                                {analyzing ? 'Regenerating...' : 'Regenerate'}
                              </button>
                            </div>
                            <div className="text-sm text-[#CCC] leading-relaxed whitespace-pre-wrap">{analysis.content}</div>
                          </div>
                        );
                      }

                      if (isProcessing) {
                        return (
                          <div className="text-center py-12">
                            <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                            <p className="text-sm text-[#888]">Generating {labels[activeTab]}...</p>
                          </div>
                        );
                      }

                      return (
                        <div className="text-center py-12">
                          <p className="text-sm text-[#666] mb-4">No {labels[activeTab]?.toLowerCase()} generated yet</p>
                          <button data-testid="generate-analysis-btn" onClick={() => handleGenerateAnalysis(activeTab)} disabled={analyzing}
                            className="px-5 py-2.5 rounded-full bg-[#007AFF] text-white text-sm font-medium hover:bg-[#0066DD] transition-colors disabled:opacity-50 inline-flex items-center gap-2">
                            {analyzing ? (
                              <>
                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                Analyzing...
                              </>
                            ) : (
                              'Generate Analysis'
                            )}
                          </button>
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right Sidebar: Clips & Annotations */}
          <div className="lg:col-span-4 space-y-4">
            {/* Clips */}
            <div className="bg-[#111] rounded-lg border border-white/10 p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#888]">
                  Clips ({clips.length})
                </h3>
                {clips.length > 0 && (
                  <button data-testid="download-highlights-btn" onClick={handleDownloadHighlights}
                    className="text-[10px] text-[#4ADE80] font-medium hover:text-[#6AEE9A]">
                    Download All
                  </button>
                )}
              </div>
              {clips.length === 0 ? (
                <div className="text-center py-6">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#333" strokeWidth="1.5" className="mx-auto mb-2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12"/></svg>
                  <p className="text-xs text-[#555]">No clips yet. Use the clip tool while watching.</p>
                </div>
              ) : (
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {clips.map(clip => (
                    <div key={clip.id} data-testid={`clip-${clip.id}`}
                      className="bg-white/[0.03] rounded-lg p-3 hover:bg-white/[0.06] transition-colors group">
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-white truncate">{clip.title}</p>
                          <p className="text-[10px] text-[#666] mt-0.5">
                            {formatTime(clip.start_time)} — {formatTime(clip.end_time)} · <span className="uppercase">{clip.clip_type}</span>
                          </p>
                        </div>
                        <button data-testid={`delete-clip-${clip.id}-btn`} onClick={() => handleDeleteClip(clip.id)}
                          className="text-[#444] hover:text-[#EF4444] opacity-0 group-hover:opacity-100 transition-opacity ml-2">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                        </button>
                      </div>
                      {clip.description && <p className="text-[10px] text-[#555] mt-1 line-clamp-2">{clip.description}</p>}
                      {clip.player_ids && clip.player_ids.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {clip.player_ids.map(pid => {
                            const player = players.find(p => p.id === pid);
                            return player ? (
                              <span key={pid} className="text-[9px] text-[#007AFF] bg-[#007AFF]/10 px-1 py-0.5 rounded">
                                #{player.number || '?'} {player.name}
                              </span>
                            ) : null;
                          })}
                        </div>
                      )}
                      <div className="flex items-center gap-3 mt-2">
                        <button data-testid={`play-clip-${clip.id}-btn`} onClick={() => playClip(clip)}
                          className="flex items-center gap-1 text-[10px] text-[#007AFF] font-medium hover:text-[#0066DD]">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                          Play
                        </button>
                        <button data-testid={`download-clip-${clip.id}-btn`}
                          onClick={() => handleDownloadClip(clip.id, clip.title)}
                          disabled={downloadingClip === clip.id}
                          className="flex items-center gap-1 text-[10px] text-[#4ADE80] font-medium hover:text-[#6AEE9A] disabled:opacity-50">
                          {downloadingClip === clip.id ? (
                            <><div className="w-2.5 h-2.5 border border-[#4ADE80] border-t-transparent rounded-full animate-spin" /> Extracting...</>
                          ) : (
                            <><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg> Download MP4</>
                          )}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Annotations */}
            <div className="bg-[#111] rounded-lg border border-white/10 p-5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[#888] mb-4">
                Annotations ({annotations.length})
              </h3>
              {annotations.length === 0 ? (
                <div className="text-center py-6">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#333" strokeWidth="1.5" className="mx-auto mb-2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                  <p className="text-xs text-[#555]">No annotations yet. Add notes while watching.</p>
                </div>
              ) : (
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {annotations.map(ann => (
                    <div key={ann.id} data-testid={`annotation-${ann.id}`}
                      className="bg-white/[0.03] rounded-lg p-3 hover:bg-white/[0.06] transition-colors group">
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded">
                            {formatTime(ann.timestamp)}
                          </span>
                          <span className="text-[10px] text-[#555] uppercase">{ann.annotation_type.replace('_', ' ')}</span>
                        </div>
                        <button data-testid={`delete-annotation-${ann.id}-btn`} onClick={() => handleDeleteAnnotation(ann.id)}
                          className="text-[#444] hover:text-[#EF4444] opacity-0 group-hover:opacity-100 transition-opacity">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                        </button>
                      </div>
                      <p className="text-xs text-[#CCC] mt-1.5">{ann.content}</p>
                      {ann.player_id && (() => {
                        const player = players.find(p => p.id === ann.player_id);
                        return player ? (
                          <span className="inline-flex items-center gap-1 mt-1 text-[10px] text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded">
                            #{player.number || '?'} {player.name}
                          </span>
                        ) : null;
                      })()}
                      <button data-testid={`seek-annotation-${ann.id}-btn`} onClick={() => seekTo(ann.timestamp)}
                        className="text-[10px] text-[#007AFF] font-medium mt-1.5 hover:text-[#0066DD]">
                        Jump to moment
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default VideoAnalysis;
