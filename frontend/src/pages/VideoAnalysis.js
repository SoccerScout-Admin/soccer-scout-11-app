import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Brain, Lightbulb, ChartLine, Users, Pen, MapPin, ChatCircleText, X, Spinner, Scissors, DownloadSimple, FilmSlate } from '@phosphor-icons/react';

const VideoAnalysis = () => {
  const { videoId } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const [videoMetadata, setVideoMetadata] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [clips, setClips] = useState([]);
  const [activeTab, setActiveTab] = useState('tactical');
  const [analyzing, setAnalyzing] = useState(false);
  const [annotationMode, setAnnotationMode] = useState(null);
  const [annotationText, setAnnotationText] = useState('');
  const [showAnnotationForm, setShowAnnotationForm] = useState(false);
  const [showClipForm, setShowClipForm] = useState(false);
  const [clipFormData, setClipFormData] = useState({ title: '', start_time: 0, end_time: 0, clip_type: 'highlight', description: '' });
  const [currentTimestamp, setCurrentTimestamp] = useState(0);

  useEffect(() => {
    fetchVideoMetadata();
    fetchAnalyses();
    fetchAnnotations();
    fetchClips();
  }, [videoId]);

  const fetchVideoMetadata = async () => {
    try {
      const response = await axios.get(`${API}/videos/${videoId}/metadata`, { headers: getAuthHeader() });
      setVideoMetadata(response.data);
    } catch (err) {
      console.error('Failed to fetch video metadata:', err);
    }
  };

  const fetchAnalyses = async () => {
    try {
      const response = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
      setAnalyses(response.data);
    } catch (err) {
      console.error('Failed to fetch analyses:', err);
    }
  };

  const fetchAnnotations = async () => {
    try {
      const response = await axios.get(`${API}/annotations/video/${videoId}`, { headers: getAuthHeader() });
      setAnnotations(response.data);
    } catch (err) {
      console.error('Failed to fetch annotations:', err);
    }
  };

  const fetchClips = async () => {
    try {
      const response = await axios.get(`${API}/clips/video/${videoId}`, { headers: getAuthHeader() });
      setClips(response.data);
    } catch (err) {
      console.error('Failed to fetch clips:', err);
    }
  };

  const handleGenerateAnalysis = async (type) => {
    setAnalyzing(true);
    try {
      await axios.post(
        `${API}/analysis/generate`,
        { video_id: videoId, analysis_type: type },
        { headers: getAuthHeader() }
      );
      fetchAnalyses();
    } catch (err) {
      console.error('Analysis failed:', err);
      alert('Analysis failed. Please try again.');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleAddAnnotation = async () => {
    if (!annotationText.trim() || !annotationMode) return;

    try {
      await axios.post(
        `${API}/annotations`,
        {
          video_id: videoId,
          timestamp: currentTimestamp,
          annotation_type: annotationMode,
          content: annotationText
        },
        { headers: getAuthHeader() }
      );
      setAnnotationText('');
      setShowAnnotationForm(false);
      setAnnotationMode(null);
      fetchAnnotations();
    } catch (err) {
      console.error('Failed to create annotation:', err);
    }
  };

  const handleDeleteAnnotation = async (annotationId) => {
    try {
      await axios.delete(`${API}/annotations/${annotationId}`, { headers: getAuthHeader() });
      fetchAnnotations();
    } catch (err) {
      console.error('Failed to delete annotation:', err);
    }
  };

  const seekToAnnotation = (timestamp) => {
    if (videoRef.current) {
      videoRef.current.currentTime = timestamp;
    }
  };

  const handleCreateClip = async () => {
    if (!clipFormData.title.trim()) {
      alert('Please enter a clip title');
      return;
    }
    
    if (clipFormData.start_time >= clipFormData.end_time) {
      alert('End time must be after start time');
      return;
    }

    try {
      await axios.post(
        `${API}/clips`,
        {
          video_id: videoId,
          ...clipFormData
        },
        { headers: getAuthHeader() }
      );
      setShowClipForm(false);
      setClipFormData({ title: '', start_time: 0, end_time: 0, clip_type: 'highlight', description: '' });
      fetchClips();
    } catch (err) {
      console.error('Failed to create clip:', err);
      alert('Failed to create clip');
    }
  };

  const handleDeleteClip = async (clipId) => {
    try {
      await axios.delete(`${API}/clips/${clipId}`, { headers: getAuthHeader() });
      fetchClips();
    } catch (err) {
      console.error('Failed to delete clip:', err);
    }
  };

  const handleDownloadHighlights = async () => {
    try {
      const response = await axios.get(`${API}/highlights/video/${videoId}`, { headers: getAuthHeader() });
      const dataStr = JSON.stringify(response.data, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = window.URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `highlights_${videoId}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to download highlights:', err);
      alert('Failed to download highlights package');
    }
  };

  const playClip = (clip) => {
    if (videoRef.current) {
      videoRef.current.currentTime = clip.start_time;
      videoRef.current.play();
      
      const handleTimeUpdate = () => {
        if (videoRef.current.currentTime >= clip.end_time) {
          videoRef.current.pause();
          videoRef.current.removeEventListener('timeupdate', handleTimeUpdate);
        }
      };
      
      videoRef.current.addEventListener('timeupdate', handleTimeUpdate);
    }
  };

  const setClipStartTime = () => {
    setClipFormData({ ...clipFormData, start_time: currentTimestamp });
  };

  const setClipEndTime = () => {
    setClipFormData({ ...clipFormData, end_time: currentTimestamp });
  };

  const getCurrentAnalysis = () => {
    return analyses.find(a => a.analysis_type === activeTab);
  };

  if (!videoMetadata) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <Spinner size={48} className="text-[#007AFF] animate-spin" />
      </div>
    );
  }

  const currentAnalysis = getCurrentAnalysis();

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center gap-4">
          <button
            data-testid="back-btn"
            onClick={() => navigate('/')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10"
          >
            <ArrowLeft size={24} className="text-white" />
          </button>
          <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Video Analysis</h1>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-[#141414] border border-white/10">
              <video
                ref={videoRef}
                data-testid="video-player"
                controls
                className="w-full"
                src={`${API}/videos/${videoId}`}
                onTimeUpdate={(e) => setCurrentTimestamp(e.target.currentTime)}
              />
            </div>

            <div className="bg-[#141414] border border-white/10 p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">Clip Tools</p>
                <button
                  data-testid="download-highlights-btn"
                  onClick={handleDownloadHighlights}
                  className="flex items-center gap-2 px-3 py-1.5 bg-[#39FF14] text-[#0A0A0A] text-xs font-bold tracking-wider uppercase hover:bg-[#2EDD0F] transition-colors"
                >
                  <DownloadSimple size={16} weight="bold" />
                  Download Highlights
                </button>
              </div>
              <div className="flex gap-3">
                <button
                  data-testid="create-clip-btn"
                  onClick={() => {
                    setShowClipForm(true);
                    setClipFormData({ ...clipFormData, start_time: currentTimestamp, end_time: currentTimestamp + 10 });
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-[#007AFF] border-[#007AFF] text-white hover:bg-[#005bb5] transition-colors"
                >
                  <Scissors size={20} />
                  <span className="text-sm font-bold tracking-wider uppercase">Create Clip</span>
                </button>
                <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-[#0A0A0A] border border-white/10 text-sm">
                  <span className="text-[#A3A3A3]">Current time:</span>
                  <span className="text-white font-mono">{Math.floor(currentTimestamp)}s</span>
                </div>
              </div>

              {showClipForm && (
                <div className="mt-4 p-4 bg-[#0A0A0A] border border-white/10">
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-sm font-bold tracking-wider uppercase text-white">Create New Clip</p>
                    <button
                      data-testid="close-clip-form-btn"
                      onClick={() => {
                        setShowClipForm(false);
                        setClipFormData({ title: '', start_time: 0, end_time: 0, clip_type: 'highlight', description: '' });
                      }}
                      className="text-[#A3A3A3] hover:text-white"
                    >
                      <X size={20} />
                    </button>
                  </div>
                  
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-bold tracking-wider uppercase text-[#A3A3A3] mb-1">Title</label>
                      <input
                        data-testid="clip-title-input"
                        type="text"
                        value={clipFormData.title}
                        onChange={(e) => setClipFormData({ ...clipFormData, title: e.target.value })}
                        className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 focus:border-[#007AFF] focus:outline-none"
                        placeholder="e.g., Amazing Goal, Tactical Play"
                      />
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-bold tracking-wider uppercase text-[#A3A3A3] mb-1">Start Time (s)</label>
                        <div className="flex gap-2">
                          <input
                            data-testid="clip-start-time-input"
                            type="number"
                            value={clipFormData.start_time}
                            onChange={(e) => setClipFormData({ ...clipFormData, start_time: parseFloat(e.target.value) })}
                            className="flex-1 bg-[#141414] border border-white/10 text-white px-3 py-2 focus:border-[#007AFF] focus:outline-none"
                            step="0.1"
                          />
                          <button
                            data-testid="set-start-time-btn"
                            onClick={setClipStartTime}
                            className="px-3 py-2 bg-[#1F1F1F] border border-white/10 text-[#007AFF] text-xs font-bold hover:bg-[#2A2A2A] transition-colors"
                          >
                            Now
                          </button>
                        </div>
                      </div>
                      
                      <div>
                        <label className="block text-xs font-bold tracking-wider uppercase text-[#A3A3A3] mb-1">End Time (s)</label>
                        <div className="flex gap-2">
                          <input
                            data-testid="clip-end-time-input"
                            type="number"
                            value={clipFormData.end_time}
                            onChange={(e) => setClipFormData({ ...clipFormData, end_time: parseFloat(e.target.value) })}
                            className="flex-1 bg-[#141414] border border-white/10 text-white px-3 py-2 focus:border-[#007AFF] focus:outline-none"
                            step="0.1"
                          />
                          <button
                            data-testid="set-end-time-btn"
                            onClick={setClipEndTime}
                            className="px-3 py-2 bg-[#1F1F1F] border border-white/10 text-[#007AFF] text-xs font-bold hover:bg-[#2A2A2A] transition-colors"
                          >
                            Now
                          </button>
                        </div>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-bold tracking-wider uppercase text-[#A3A3A3] mb-1">Type</label>
                      <select
                        data-testid="clip-type-select"
                        value={clipFormData.clip_type}
                        onChange={(e) => setClipFormData({ ...clipFormData, clip_type: e.target.value })}
                        className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 focus:border-[#007AFF] focus:outline-none"
                      >
                        <option value="highlight">Highlight</option>
                        <option value="goal">Goal</option>
                        <option value="save">Save</option>
                        <option value="tactical">Tactical Play</option>
                        <option value="mistake">Mistake</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-bold tracking-wider uppercase text-[#A3A3A3] mb-1">Description (Optional)</label>
                      <textarea
                        data-testid="clip-description-input"
                        value={clipFormData.description}
                        onChange={(e) => setClipFormData({ ...clipFormData, description: e.target.value })}
                        className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 focus:border-[#007AFF] focus:outline-none resize-none"
                        rows="2"
                        placeholder="Add any notes about this clip..."
                      />
                    </div>

                    <button
                      data-testid="save-clip-btn"
                      onClick={handleCreateClip}
                      className="w-full bg-[#007AFF] hover:bg-[#005bb5] text-white px-4 py-2 text-sm font-bold tracking-wider uppercase transition-colors"
                    >
                      Save Clip
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="bg-[#141414] border border-white/10 p-4">
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider mb-3">Annotation Tools</p>
              <div className="flex gap-3">
                <button
                  data-testid="note-tool-btn"
                  onClick={() => {
                    setAnnotationMode('note');
                    setShowAnnotationForm(true);
                  }}
                  className={`flex items-center gap-2 px-4 py-2 border transition-colors ${
                    annotationMode === 'note'
                      ? 'bg-[#007AFF] border-[#007AFF] text-white'
                      : 'bg-transparent border-white/10 text-[#A3A3A3] hover:border-white/20'
                  }`}
                >
                  <ChatCircleText size={20} />
                  <span className="text-sm font-bold tracking-wider uppercase">Note</span>
                </button>
                <button
                  data-testid="tactical-tool-btn"
                  onClick={() => {
                    setAnnotationMode('tactical');
                    setShowAnnotationForm(true);
                  }}
                  className={`flex items-center gap-2 px-4 py-2 border transition-colors ${
                    annotationMode === 'tactical'
                      ? 'bg-[#007AFF] border-[#007AFF] text-white'
                      : 'bg-transparent border-white/10 text-[#A3A3A3] hover:border-white/20'
                  }`}
                >
                  <MapPin size={20} />
                  <span className="text-sm font-bold tracking-wider uppercase">Tactical</span>
                </button>
                <button
                  data-testid="key-moment-tool-btn"
                  onClick={() => {
                    setAnnotationMode('key_moment');
                    setShowAnnotationForm(true);
                  }}
                  className={`flex items-center gap-2 px-4 py-2 border transition-colors ${
                    annotationMode === 'key_moment'
                      ? 'bg-[#007AFF] border-[#007AFF] text-white'
                      : 'bg-transparent border-white/10 text-[#A3A3A3] hover:border-white/20'
                  }`}
                >
                  <Lightbulb size={20} />
                  <span className="text-sm font-bold tracking-wider uppercase">Key Moment</span>
                </button>
              </div>

              {showAnnotationForm && (
                <div className="mt-4 p-4 bg-[#0A0A0A] border border-white/10">
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-sm font-bold tracking-wider uppercase text-[#A3A3A3]">
                      Add {annotationMode?.replace('_', ' ')} at {Math.floor(currentTimestamp)}s
                    </p>
                    <button
                      data-testid="close-annotation-form-btn"
                      onClick={() => {
                        setShowAnnotationForm(false);
                        setAnnotationMode(null);
                        setAnnotationText('');
                      }}
                      className="text-[#A3A3A3] hover:text-white"
                    >
                      <X size={20} />
                    </button>
                  </div>
                  <textarea
                    data-testid="annotation-text-input"
                    value={annotationText}
                    onChange={(e) => setAnnotationText(e.target.value)}
                    className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 mb-3 focus:border-[#007AFF] focus:outline-none resize-none"
                    rows="3"
                    placeholder="Enter your annotation..."
                  />
                  <button
                    data-testid="save-annotation-btn"
                    onClick={handleAddAnnotation}
                    className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-4 py-2 text-sm font-bold tracking-wider uppercase transition-colors"
                  >
                    Save Annotation
                  </button>
                </div>
              )}
            </div>

            <div className="bg-[#141414] border border-white/10 p-6">
              <div className="flex gap-2 mb-6 border-b border-white/10">
                <button
                  data-testid="tactical-tab-btn"
                  onClick={() => setActiveTab('tactical')}
                  className={`px-4 py-3 text-sm font-bold tracking-wider uppercase transition-colors ${
                    activeTab === 'tactical'
                      ? 'text-white border-b-2 border-[#007AFF]'
                      : 'text-[#A3A3A3] hover:text-white'
                  }`}
                >
                  <Brain className="inline mr-2" size={20} />
                  Tactical
                </button>
                <button
                  data-testid="player-tab-btn"
                  onClick={() => setActiveTab('player_performance')}
                  className={`px-4 py-3 text-sm font-bold tracking-wider uppercase transition-colors ${
                    activeTab === 'player_performance'
                      ? 'text-white border-b-2 border-[#007AFF]'
                      : 'text-[#A3A3A3] hover:text-white'
                  }`}
                >
                  <Users className="inline mr-2" size={20} />
                  Players
                </button>
                <button
                  data-testid="highlights-tab-btn"
                  onClick={() => setActiveTab('highlights')}
                  className={`px-4 py-3 text-sm font-bold tracking-wider uppercase transition-colors ${
                    activeTab === 'highlights'
                      ? 'text-white border-b-2 border-[#007AFF]'
                      : 'text-[#A3A3A3] hover:text-white'
                  }`}
                >
                  <Lightbulb className="inline mr-2" size={20} />
                  Highlights
                </button>
              </div>

              {currentAnalysis ? (
                <div data-testid="analysis-content" className="prose prose-invert max-w-none">
                  <div className="text-[#A3A3A3] whitespace-pre-wrap leading-relaxed">{currentAnalysis.content}</div>
                </div>
              ) : (
                <div className="text-center py-12">
                  <ChartLine size={64} className="text-[#A3A3A3] mx-auto mb-4" />
                  <p className="text-[#A3A3A3] mb-4">No {activeTab.replace('_', ' ')} analysis yet</p>
                  <button
                    data-testid="generate-analysis-btn"
                    onClick={() => handleGenerateAnalysis(activeTab)}
                    disabled={analyzing}
                    className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors disabled:opacity-50 inline-flex items-center gap-2"
                  >
                    {analyzing ? (
                      <>
                        <Spinner size={20} className="animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <Brain size={20} />
                        Generate AI Analysis
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-6">
            <div className="bg-[#141414] border border-white/10 p-6">
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider mb-4">Annotations</p>
              {annotations.length === 0 ? (
                <p className="text-sm text-[#A3A3A3] text-center py-8">No annotations yet</p>
              ) : (
                <div className="space-y-3">
                  {annotations.map((annotation) => (
                    <div
                      key={annotation.id}
                      data-testid={`annotation-${annotation.id}`}
                      className="bg-[#0A0A0A] border border-white/10 p-3 hover:border-white/20 transition-colors"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <span className="text-xs font-bold tracking-wider uppercase text-[#007AFF]">
                          {Math.floor(annotation.timestamp)}s
                        </span>
                        <button
                          data-testid={`delete-annotation-${annotation.id}-btn`}
                          onClick={() => handleDeleteAnnotation(annotation.id)}
                          className="text-[#FF3B30] hover:text-[#FF6B60] text-xs"
                        >
                          <X size={16} />
                        </button>
                      </div>
                      <p className="text-xs text-[#A3A3A3] uppercase tracking-wider mb-1">{annotation.annotation_type.replace('_', ' ')}</p>
                      <p className="text-sm text-white mb-2">{annotation.content}</p>
                      <button
                        data-testid={`seek-annotation-${annotation.id}-btn`}
                        onClick={() => seekToAnnotation(annotation.timestamp)}
                        className="text-xs text-[#007AFF] hover:text-[#005bb5] font-bold tracking-wider uppercase"
                      >
                        Jump to timestamp
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-[#141414] border border-white/10 p-6">
              <div className="flex items-center gap-2 mb-4">
                <FilmSlate size={20} className="text-[#39FF14]" />
                <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">Video Clips ({clips.length})</p>
              </div>
              {clips.length === 0 ? (
                <p className="text-sm text-[#A3A3A3] text-center py-8">No clips created yet</p>
              ) : (
                <div className="space-y-3">
                  {clips.map((clip) => (
                    <div
                      key={clip.id}
                      data-testid={`clip-${clip.id}`}
                      className="bg-[#0A0A0A] border border-white/10 p-3 hover:border-white/20 transition-colors"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex-1">
                          <h4 className="text-sm font-bold text-white mb-1">{clip.title}</h4>
                          <div className="flex items-center gap-2 text-xs text-[#A3A3A3]">
                            <span>{Math.floor(clip.start_time)}s - {Math.floor(clip.end_time)}s</span>
                            <span>•</span>
                            <span className="uppercase">{clip.clip_type}</span>
                          </div>
                        </div>
                        <button
                          data-testid={`delete-clip-${clip.id}-btn`}
                          onClick={() => handleDeleteClip(clip.id)}
                          className="text-[#FF3B30] hover:text-[#FF6B60] text-xs"
                        >
                          <X size={16} />
                        </button>
                      </div>
                      {clip.description && (
                        <p className="text-xs text-[#A3A3A3] mb-2">{clip.description}</p>
                      )}
                      <button
                        data-testid={`play-clip-${clip.id}-btn`}
                        onClick={() => playClip(clip)}
                        className="text-xs text-[#007AFF] hover:text-[#005bb5] font-bold tracking-wider uppercase flex items-center gap-1"
                      >
                        <FilmSlate size={14} />
                        Play Clip
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
