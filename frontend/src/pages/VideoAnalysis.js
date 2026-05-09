import { useState, useRef, useMemo, useCallback, useEffect } from 'react';
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
import ClipCreateForm from './components/ClipCreateForm';
import VideoToolbar from './components/VideoToolbar';
import DataIntegrityBanner from './components/DataIntegrityBanner';
import { useClipShare, useClipCollection, useClipTagging } from './components/hooks/useClipActions';
import { useVideoProcessing, useVideoData } from './components/hooks/useVideoProcessing';

const PROCESSING_LABEL = {
  tactical: 'Tactical Analysis',
  player_performance: 'Player Ratings',
  highlights: 'Highlights Detection',
  timeline_markers: 'Timeline Markers',
};

const VideoAnalysis = () => {
  const { videoId } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef(null);

  const {
    videoMetadata, match, analyses, setAnalyses,
    annotations, setAnnotations, clips, setClips,
    players, markers, setMarkers, videoSrc,
  } = useVideoData(videoId);

  const onAnalysesRefresh = useCallback((a) => setAnalyses(a), [setAnalyses]);
  const onMarkersRefresh = useCallback((m) => setMarkers(m), [setMarkers]);

  const {
    processingStatus, serverRestarted,
    isProcessing, isProcessed, processingFailed,
    reprocess: handleReprocess,
  } = useVideoProcessing(videoId, onAnalysesRefresh, onMarkersRefresh);

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
  const [showTrimPanel, setShowTrimPanel] = useState(false);
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [downloadingClip, setDownloadingClip] = useState(null);
  const [selectedClips, setSelectedClips] = useState([]);
  const [downloadingZip, setDownloadingZip] = useState(false);

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

  const [mentionedCoaches, setMentionedCoaches] = useState([]);

  const {
    taggingClip, setTaggingClip, tagSearch, setTagSearch,
    tagSelection, savingTags, aiSuggesting, aiSuggestions,
    openTagModal, handleAiSuggest, toggleTag, saveClipTags,
  } = useClipTagging(setClips);

  const {
    collectionShare, setCollectionShare,
    collectionModalOpen, setCollectionModalOpen,
    collectionTitle, setCollectionTitle,
    collectionDescription, setCollectionDescription,
    creatingCollection, collectionCopied,
    collectionUrl, handleCreateCollection, copyCollectionUrl,
  } = useClipCollection(selectedClips, mentionedCoaches);

  const {
    sharingClip, setSharingClip, clipShareCopied,
    handleShareClip, handleRevokeClipShare, copyClipShareLink, shareClipTo,
  } = useClipShare(setClips);

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

  const handleGenerateCloseUp = async (clip) => {
    const isFailed = clip.close_up_status === 'failed';
    const url = isFailed
      ? `${API}/clips/${clip.id}/close-up/retry`
      : `${API}/clips/${clip.id}/generate-close-up`;
    try {
      const res = await axios.post(url, {}, { headers: getAuthHeader() });
      // Optimistically reflect the new status in the sidebar so the user sees
      // the "Generating close-up" badge immediately.
      const newStatus = res.data?.status || 'pending';
      setClips((prev) => prev.map((c) =>
        c.id === clip.id ? { ...c, close_up_status: newStatus } : c
      ));
    } catch (err) {
      const detail = err.response?.data?.detail;
      alert('Could not start close-up: ' + (typeof detail === 'string' ? detail : err.message));
    }
  };

  // Poll backend every 8s while any clip is in-flight so the UI flips to the
  // "🎬 Wide + Close-up" badge as soon as ffmpeg finishes. Stops automatically
  // when no clip is processing/pending.
  useEffect(() => {
    const inflight = (clips || []).some((c) =>
      c.close_up_status === 'pending' || c.close_up_status === 'processing'
    );
    if (!inflight) return;
    const tick = setInterval(async () => {
      try {
        const res = await axios.get(`${API}/clips/video/${videoId}`, { headers: getAuthHeader() });
        setClips(res.data || []);
      } catch (err) { /* poll silently */ }
    }, 8000);
    return () => clearInterval(tick);
  }, [clips, videoId]);

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

  const processingLabel = PROCESSING_LABEL;

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
        <DataIntegrityBanner videoMetadata={videoMetadata} />

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

            <VideoToolbar
              videoId={videoId}
              currentTimestamp={currentTimestamp}
              videoDuration={videoDuration}
              clipFormData={clipFormData}
              setClipFormData={setClipFormData}
              setShowClipForm={setShowClipForm}
              annotationMode={annotationMode}
              setAnnotationMode={setAnnotationMode}
              setShowAnnotationForm={setShowAnnotationForm}
              onAnnotationAdded={(ann) => setAnnotations((prev) => [ann, ...prev])}
              showTrimPanel={showTrimPanel}
              setShowTrimPanel={setShowTrimPanel}
              setTrimStart={setTrimStart}
              setTrimEnd={setTrimEnd}
            />

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
              <ClipCreateForm
                clipFormData={clipFormData}
                setClipFormData={setClipFormData}
                currentTimestamp={currentTimestamp}
                players={players}
                selectedClipPlayerIds={selectedClipPlayerIds}
                setSelectedClipPlayerIds={setSelectedClipPlayerIds}
                onClose={() => setShowClipForm(false)}
                onSave={handleCreateClip}
              />
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
              onGenerateCloseUp={handleGenerateCloseUp}
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
