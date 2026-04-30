import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import TagPlayersModal from './components/TagPlayersModal';
import ShareReelModal from './components/ShareReelModal';
import ShareClipModal from './components/ShareClipModal';
import VideoPlayerWithMarkers from './components/VideoPlayerWithMarkers';
import AnalysisTabs from './components/AnalysisTabs';
import VideoAnalysisHeader from './components/VideoAnalysisHeader';
import TrimPanel from './components/TrimPanel';
import ClipsSidebar from './components/ClipsSidebar';
import AnnotationsSidebar from './components/AnnotationsSidebar';
import AnnotationForm from './components/AnnotationForm';
import LiveCoachingMic from './components/LiveCoachingMic';

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
  const [videoSrc, setVideoSrc] = useState('');
  const [markers, setMarkers] = useState([]);
  const [showTrimPanel, setShowTrimPanel] = useState(false);
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [downloadingClip, setDownloadingClip] = useState(null);
  const [selectedClips, setSelectedClips] = useState([]);
  const [downloadingZip, setDownloadingZip] = useState(false);
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
        // Get short-lived video access token (avoids exposing main JWT in video URL)
        try {
          const tokenRes = await axios.get(`${API}/videos/${videoId}/access-token`, { headers: getAuthHeader() });
          setVideoSrc(`${API}/videos/${videoId}?token=${tokenRes.data.token}`);
        } catch (e) {
          console.error('Failed to get video access token:', e);
          setVideoSrc(`${API}/videos/${videoId}`);
        }
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
        } catch (e) { console.error('Failed to refresh markers after processing:', e); }
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

  const handleDownloadZip = async (clipIds) => {
    setDownloadingZip(true);
    try {
      const response = await axios.post(`${API}/clips/download-zip`, { clip_ids: clipIds }, {
        headers: getAuthHeader(),
        responseType: 'blob',
        timeout: 900000
      });
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/zip' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'highlights.zip';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert('Failed to download ZIP. ' + (err.response?.data?.detail || err.message));
    } finally {
      setDownloadingZip(false);
    }
  };

  const toggleClipSelection = (clipId) => {
    setSelectedClips(prev => prev.includes(clipId) ? prev.filter(id => id !== clipId) : [...prev, clipId]);
  };

  const [collectionShare, setCollectionShare] = useState(null);
  const [collectionModalOpen, setCollectionModalOpen] = useState(false);
  const [collectionTitle, setCollectionTitle] = useState('');
  const [collectionDescription, setCollectionDescription] = useState('');
  const [mentionedCoaches, setMentionedCoaches] = useState([]);
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [collectionCopied, setCollectionCopied] = useState(false);

  const [taggingClip, setTaggingClip] = useState(null);
  const [tagSearch, setTagSearch] = useState('');
  const [tagSelection, setTagSelection] = useState([]);
  const [savingTags, setSavingTags] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState(null);

  const openTagModal = (clip) => {
    setTaggingClip(clip);
    setTagSelection(clip.player_ids || []);
    setTagSearch('');
    setAiSuggestions(null);
  };

  const handleAiSuggest = async () => {
    if (!taggingClip) return;
    setAiSuggesting(true);
    try {
      const res = await axios.post(`${API}/clips/${taggingClip.id}/ai-suggest-tags`, {}, { headers: getAuthHeader() });
      setAiSuggestions(res.data);
      // Pre-select any matched players (coach can de-select before saving)
      const ids = Array.from(new Set([...tagSelection, ...res.data.suggestions.map(s => s.player_id)]));
      setTagSelection(ids);
    } catch (err) {
      alert('AI tagging failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setAiSuggesting(false);
    }
  };

  const toggleTag = (playerId) => {
    setTagSelection(prev =>
      prev.includes(playerId) ? prev.filter(id => id !== playerId) : [...prev, playerId]
    );
  };

  const saveClipTags = async () => {
    if (!taggingClip) return;
    setSavingTags(true);
    try {
      await axios.patch(`${API}/clips/${taggingClip.id}`, { player_ids: tagSelection }, { headers: getAuthHeader() });
      setClips(prev => prev.map(c =>
        c.id === taggingClip.id ? { ...c, player_ids: tagSelection } : c
      ));
      setTaggingClip(null);
    } catch (err) {
      alert('Failed to save tags: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSavingTags(false);
    }
  };

  const handleCreateCollection = async () => {
    if (selectedClips.length === 0) return;
    setCreatingCollection(true);
    try {
      const res = await axios.post(`${API}/clip-collections`, {
        clip_ids: selectedClips,
        title: collectionTitle.trim() || `${selectedClips.length} Clips`,
        description: (collectionDescription || '').trim(),
        mentioned_coach_ids: mentionedCoaches.map((c) => c.id),
      }, { headers: getAuthHeader() });
      setCollectionShare(res.data);
    } catch (err) {
      alert('Failed to create reel: ' + (err.response?.data?.detail || err.message));
    } finally {
      setCreatingCollection(false);
    }
  };

  const collectionUrl = collectionShare
    ? `${window.location.origin}/api/og/clip-collection/${collectionShare.share_token}`
    : '';

  const copyCollectionUrl = async () => {
    if (!collectionUrl) return;
    try {
      await navigator.clipboard.writeText(collectionUrl);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = collectionUrl; document.body.appendChild(ta);
      ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    }
    setCollectionCopied(true);
    setTimeout(() => setCollectionCopied(false), 2000);
  };

  const [sharingClip, setSharingClip] = useState(null);
  const [clipShareCopied, setClipShareCopied] = useState(false);

  const handleShareClip = async (clip) => {
    if (clip.share_token) {
      // Already shared — show the modal
      setSharingClip(clip);
      return;
    }
    try {
      const res = await axios.post(`${API}/clips/${clip.id}/share`, {}, { headers: getAuthHeader() });
      if (res.data.share_token) {
        const updated = { ...clip, share_token: res.data.share_token };
        setSharingClip(updated);
        // Update clips list
        setClips(prev => prev.map(c => c.id === clip.id ? { ...c, share_token: res.data.share_token } : c));
      }
    } catch (err) {
      alert('Failed to generate share link');
    }
  };

  const handleRevokeClipShare = async () => {
    if (!sharingClip) return;
    try {
      await axios.post(`${API}/clips/${sharingClip.id}/share`, {}, { headers: getAuthHeader() });
      setClips(prev => prev.map(c => c.id === sharingClip.id ? { ...c, share_token: null } : c));
      setSharingClip(null);
    } catch (err) {
      alert('Failed to revoke share link');
    }
  };

  const copyClipShareLink = () => {
    const url = `${window.location.origin}/api/og/clip/${sharingClip.share_token}`;
    try {
      navigator.clipboard.writeText(url).then(() => {
        setClipShareCopied(true);
        setTimeout(() => setClipShareCopied(false), 2000);
      }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = url;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        setClipShareCopied(true);
        setTimeout(() => setClipShareCopied(false), 2000);
      });
    } catch (e) {
      console.error('Clipboard copy failed:', e);
    }
  };

  const shareClipTo = (platform) => {
    const url = `${window.location.origin}/api/og/clip/${sharingClip.share_token}`;
    const text = `${sharingClip.title} — Soccer Scout`;
    const links = {
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
      instagram: url,
      youtube: url,
      sms: `sms:?body=${encodeURIComponent(`${text}: ${url}`)}`
    };
    if (platform === 'instagram' || platform === 'youtube') {
      copyClipShareLink();
      return;
    }
    window.open(links[platform], '_blank', 'width=600,height=400');
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

  const isProcessing = processingStatus && (processingStatus.processing_status === 'processing' || processingStatus.processing_status === 'queued');
  const isProcessed = processingStatus && processingStatus.processing_status === 'completed';
  const processingFailed = processingStatus && processingStatus.processing_status === 'failed';

  const processingLabel = {
    'tactical': 'Tactical Analysis',
    'player_performance': 'Player Ratings',
    'highlights': 'Highlights Detection',
    'timeline_markers': 'Timeline Markers'
  };

  const sortedMarkers = useMemo(() =>
    [...markers].sort((a, b) => a.time - b.time),
    [markers]
  );

  if (!videoMetadata) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-10 h-10 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" style={{ fontFamily: 'Inter, sans-serif' }}>
      <VideoAnalysisHeader
        match={match}
        videoMetadata={videoMetadata}
        isProcessing={isProcessing}
        isProcessed={isProcessed}
        processingFailed={processingFailed}
        processingStatus={processingStatus}
        serverRestarted={serverRestarted}
        processingLabel={processingLabel}
        onBack={() => navigate('/')}
        onDownloadHighlights={handleDownloadHighlights}
        onReprocess={handleReprocess}
      />

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
            <VideoPlayerWithMarkers
              ref={videoRef}
              videoSrc={videoSrc}
              markers={markers}
              videoDuration={videoDuration}
              onTimeUpdate={setCurrentTimestamp}
              onLoadedMetadata={setVideoDuration}
              onSeek={seekTo}
            />

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
              {/* Inline Live Coaching mic (desktop) */}
              <div className="hidden sm:block">
                <LiveCoachingMic
                  videoId={videoId}
                  videoCurrentTime={currentTimestamp}
                  isMobile={false}
                  onAnnotationAdded={(ann) => setAnnotations((prev) => [ann, ...prev])}
                />
              </div>
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
              <TrimPanel
                trimStart={trimStart}
                setTrimStart={setTrimStart}
                trimEnd={trimEnd}
                setTrimEnd={setTrimEnd}
                videoDuration={videoDuration}
                currentTimestamp={currentTimestamp}
                analyzing={analyzing}
                processingLabel={processingLabel}
                onClose={() => setShowTrimPanel(false)}
                onAnalyze={handleTrimmedAnalysis}
              />
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
              <AnnotationForm
                annotationMode={annotationMode}
                currentTimestamp={currentTimestamp}
                annotationText={annotationText}
                setAnnotationText={setAnnotationText}
                selectedPlayerId={selectedPlayerId}
                setSelectedPlayerId={setSelectedPlayerId}
                players={players}
                onClose={() => { setShowAnnotationForm(false); setAnnotationMode(null); setAnnotationText(''); }}
                onSave={handleAddAnnotation}
              />
            )}

            {/* Analysis Tabs */}
            <AnalysisTabs
              activeTab={activeTab}
              onSelectTab={setActiveTab}
              analyses={analyses}
              markers={markers}
              sortedMarkers={sortedMarkers}
              isProcessing={isProcessing}
              isProcessed={isProcessed}
              processingStatus={processingStatus}
              analyzing={analyzing}
              onGenerate={handleGenerateAnalysis}
              onStart={handleReprocess}
              onSeek={seekTo}
            />
          </div>

          {/* Right Sidebar: Clips & Annotations */}
          <div className="lg:col-span-4 space-y-4">
            <ClipsSidebar
              clips={clips}
              players={players}
              selectedClips={selectedClips}
              downloadingClip={downloadingClip}
              downloadingZip={downloadingZip}
              onToggleSelect={toggleClipSelection}
              onShareReel={() => {
                setCollectionTitle('');
                setCollectionDescription('');
                setMentionedCoaches([]);
                setCollectionShare(null);
                setCollectionCopied(false);
                setCollectionModalOpen(true);
              }}
              onDownloadZipSelected={() => handleDownloadZip(selectedClips)}
              onDownloadAllZip={() => handleDownloadZip(clips.map(c => c.id))}
              onDeleteClip={handleDeleteClip}
              onPlayClip={playClip}
              onDownloadClip={handleDownloadClip}
              onTagClip={openTagModal}
              onShareClip={handleShareClip}
            />
            <AnnotationsSidebar
              annotations={annotations}
              players={players}
              onDelete={handleDeleteAnnotation}
              onSeek={seekTo}
            />
          </div>
        </div>
      </main>

      {/* Clip Share Modal */}
      <ShareClipModal
        sharingClip={sharingClip}
        setSharingClip={setSharingClip}
        copyClipShareLink={copyClipShareLink}
        clipShareCopied={clipShareCopied}
        shareClipTo={shareClipTo}
        handleRevokeClipShare={handleRevokeClipShare}
      />

      {/* Clip Reel (batch share) Modal */}
      <ShareReelModal
        collectionModalOpen={collectionModalOpen}
        setCollectionModalOpen={setCollectionModalOpen}
        collectionShare={collectionShare}
        selectedClips={selectedClips}
        collectionTitle={collectionTitle}
        setCollectionTitle={setCollectionTitle}
        description={collectionDescription}
        setDescription={setCollectionDescription}
        mentionedCoaches={mentionedCoaches}
        setMentionedCoaches={setMentionedCoaches}
        handleCreateCollection={handleCreateCollection}
        creatingCollection={creatingCollection}
        collectionUrl={collectionUrl}
        copyCollectionUrl={copyCollectionUrl}
        collectionCopied={collectionCopied}
      />

      {/* Tag Players Modal */}
      <TagPlayersModal
        taggingClip={taggingClip}
        setTaggingClip={setTaggingClip}
        tagSearch={tagSearch}
        setTagSearch={setTagSearch}
        tagSelection={tagSelection}
        toggleTag={toggleTag}
        savingTags={savingTags}
        saveClipTags={saveClipTags}
        aiSuggesting={aiSuggesting}
        aiSuggestions={aiSuggestions}
        handleAiSuggest={handleAiSuggest}
        players={players}
      />

      {/* Mobile FAB — Live Coaching mic */}
      <div className="sm:hidden">
        <LiveCoachingMic
          videoId={videoId}
          videoCurrentTime={currentTimestamp}
          isMobile={true}
          onAnnotationAdded={(ann) => setAnnotations((prev) => [ann, ...prev])}
        />
      </div>
    </div>
  );
};

export default VideoAnalysis;
