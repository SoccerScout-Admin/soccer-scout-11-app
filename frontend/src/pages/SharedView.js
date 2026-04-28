import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Play, Trophy, CalendarBlank, VideoCamera, Users, ArrowLeft, Link as LinkIcon } from '@phosphor-icons/react';

const SharedView = () => {
  const { shareToken } = useParams();
  const navigate = useNavigate();
  const [folderData, setFolderData] = useState(null);
  const [selectedMatch, setSelectedMatch] = useState(null);
  const [matchDetail, setMatchDetail] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const videoRef = useRef(null);

  useEffect(() => {
    fetchFolder();
  }, [shareToken]);

  const fetchFolder = async () => {
    try {
      const res = await axios.get(`${API}/shared/${shareToken}`);
      setFolderData(res.data);
    } catch (err) {
      setError(err.response?.status === 404 ? 'This shared link is no longer available or has expired.' : 'Failed to load shared content.');
    } finally {
      setLoading(false);
    }
  };

  const openMatch = async (matchId) => {
    setSelectedMatch(matchId);
    setActiveTab('overview');
    try {
      const res = await axios.get(`${API}/shared/${shareToken}/match/${matchId}`);
      setMatchDetail(res.data);
    } catch (err) {
      console.error('Failed to load match:', err);
    }
  };

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const seekTo = (time) => { if (videoRef.current) videoRef.current.currentTime = time; };

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

  const getAnalysis = (type) => matchDetail?.analyses?.find(a => a.analysis_type === type);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-10 h-10 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center text-center px-6">
        <div>
          <LinkIcon size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Link Unavailable</h1>
          <p className="text-[#A3A3A3] mb-6">{error}</p>
          <button data-testid="shared-go-home-btn" onClick={() => navigate('/auth')}
            className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors">
            Go to Soccer Scout
          </button>
        </div>
      </div>
    );
  }

  // Match detail view
  if (selectedMatch && matchDetail) {
    const { match, analyses, clips, annotations, players, video, folder_name } = matchDetail;
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white" style={{ fontFamily: 'Inter, sans-serif' }}>
        <header className="sticky top-0 z-50 bg-[#0A0A0A]/95 backdrop-blur-sm border-b border-white/5 px-6 py-3">
          <div className="max-w-[1400px] mx-auto flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button data-testid="shared-back-btn" onClick={() => { setSelectedMatch(null); setMatchDetail(null); }}
                className="p-2 rounded-lg hover:bg-white/5 transition-colors">
                <ArrowLeft size={20} />
              </button>
              <div>
                <h1 className="text-lg font-semibold" style={{ fontFamily: 'Space Grotesk' }}>
                  {match.team_home} vs {match.team_away}
                </h1>
                <p className="text-xs text-[#888]">{match.competition || 'Friendly'} — {new Date(match.date).toLocaleDateString()}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-[#666] bg-white/5 px-3 py-1.5 rounded-full uppercase tracking-wider">
                Shared from {folder_name}
              </span>
            </div>
          </div>
        </header>

        <main className="max-w-[1400px] mx-auto px-6 py-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Video + Analysis */}
            <div className="lg:col-span-8 space-y-4">
              {video && (
                <div className="bg-black rounded-lg overflow-hidden">
                  <video ref={videoRef} data-testid="shared-video-player" controls
                    className="w-full aspect-video"
                    src={`${API}/shared/${shareToken}/video/${video.id}`}
                    preload="auto" />
                </div>
              )}

              {/* Analysis Tabs */}
              <div className="bg-[#111] rounded-lg border border-white/10">
                <div className="flex border-b border-white/5">
                  {[['overview', 'Overview'], ['tactical', 'Tactical'], ['player_performance', 'Players'], ['highlights', 'Highlights']].map(([key, label]) => (
                    <button key={key} data-testid={`shared-${key}-tab`} onClick={() => setActiveTab(key)}
                      className={`px-5 py-3.5 text-xs font-semibold uppercase tracking-wider transition-colors relative ${
                        activeTab === key ? 'text-white' : 'text-[#666] hover:text-[#AAA]'
                      }`}>
                      {label}
                      {activeTab === key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#007AFF]" />}
                      {key !== 'overview' && getAnalysis(key) && <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-[#4ADE80] inline-block" />}
                    </button>
                  ))}
                </div>
                <div className="p-6">
                  {activeTab === 'overview' ? (
                    <div data-testid="shared-overview">
                      <h3 className="text-base font-semibold mb-4" style={{ fontFamily: 'Space Grotesk' }}>Analysis Summary</h3>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {['tactical', 'player_performance', 'highlights'].map(type => {
                          const analysis = getAnalysis(type);
                          const labels = { tactical: 'Tactical Analysis', player_performance: 'Player Ratings', highlights: 'Highlights' };
                          return (
                            <div key={type} data-testid={`shared-overview-${type}`}
                              className={`rounded-lg border p-4 cursor-pointer transition-colors ${
                                analysis ? 'border-[#4ADE80]/20 bg-[#0A1A0A] hover:bg-[#0A200A]' : 'border-white/5 bg-white/[0.02]'
                              }`}
                              onClick={() => analysis && setActiveTab(type)}>
                              <span className="text-xs font-semibold uppercase tracking-wider text-[#888]">{labels[type]}</span>
                              {analysis ? (
                                <p className="text-xs text-[#AAA] line-clamp-3 mt-2">{analysis.content.substring(0, 150)}...</p>
                              ) : (
                                <p className="text-xs text-[#555] mt-2">Not available</p>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      {/* Roster */}
                      {players && players.length > 0 && (
                        <div className="mt-6">
                          <h4 className="text-xs font-semibold uppercase tracking-wider text-[#888] mb-3 flex items-center gap-2">
                            <Users size={14} /> Roster ({players.length})
                          </h4>
                          <div className="flex flex-wrap gap-2">
                            {players.sort((a, b) => (a.number || 99) - (b.number || 99)).map(p => (
                              <span key={p.id} className="inline-flex items-center gap-1.5 bg-white/5 px-3 py-1.5 text-xs text-[#CCC]">
                                <span className="text-[#007AFF] font-bold">#{p.number || '?'}</span>
                                {p.name}
                                {p.position && <span className="text-[#666]">({p.position})</span>}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div data-testid={`shared-${activeTab}-content`}>
                      {(() => {
                        const analysis = getAnalysis(activeTab);
                        const labels = { tactical: 'Tactical Analysis', player_performance: 'Player Performance', highlights: 'Match Highlights' };
                        if (analysis) {
                          return (
                            <div>
                              <h3 className="text-base font-semibold mb-4" style={{ fontFamily: 'Space Grotesk' }}>{labels[activeTab]}</h3>
                              <div className="text-sm text-[#CCC] leading-relaxed whitespace-pre-wrap">{analysis.content}</div>
                            </div>
                          );
                        }
                        return <p className="text-sm text-[#666] text-center py-12">No {labels[activeTab]?.toLowerCase()} available for this match.</p>;
                      })()}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Right Sidebar */}
            <div className="lg:col-span-4 space-y-4">
              {/* Clips */}
              <div className="bg-[#111] rounded-lg border border-white/10 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#888] mb-4">
                  Clips ({clips?.length || 0})
                </h3>
                {(!clips || clips.length === 0) ? (
                  <p className="text-xs text-[#555] text-center py-4">No clips for this match.</p>
                ) : (
                  <div className="space-y-2 max-h-[400px] overflow-y-auto">
                    {clips.map(clip => (
                      <div key={clip.id} data-testid={`shared-clip-${clip.id}`}
                        className="bg-white/[0.03] rounded-lg p-3 hover:bg-white/[0.06] transition-colors">
                        <p className="text-sm font-medium text-white truncate">{clip.title}</p>
                        <p className="text-[10px] text-[#666] mt-0.5">
                          {formatTime(clip.start_time)} — {formatTime(clip.end_time)} · <span className="uppercase">{clip.clip_type}</span>
                        </p>
                        {clip.player_ids && clip.player_ids.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {clip.player_ids.map(pid => {
                              const player = players?.find(p => p.id === pid);
                              return player ? (
                                <span key={pid} className="text-[9px] text-[#007AFF] bg-[#007AFF]/10 px-1 py-0.5 rounded">
                                  #{player.number || '?'} {player.name}
                                </span>
                              ) : null;
                            })}
                          </div>
                        )}
                        <button data-testid={`shared-play-clip-${clip.id}`} onClick={() => playClip(clip)}
                          className="flex items-center gap-1 mt-2 text-[10px] text-[#007AFF] font-medium hover:text-[#0066DD]">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                          Play
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Annotations */}
              <div className="bg-[#111] rounded-lg border border-white/10 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#888] mb-4">
                  Annotations ({annotations?.length || 0})
                </h3>
                {(!annotations || annotations.length === 0) ? (
                  <p className="text-xs text-[#555] text-center py-4">No annotations for this match.</p>
                ) : (
                  <div className="space-y-2 max-h-[400px] overflow-y-auto">
                    {annotations.map(ann => (
                      <div key={ann.id} data-testid={`shared-annotation-${ann.id}`}
                        className="bg-white/[0.03] rounded-lg p-3 hover:bg-white/[0.06] transition-colors">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded">
                            {formatTime(ann.timestamp)}
                          </span>
                          <span className="text-[10px] text-[#555] uppercase">{ann.annotation_type?.replace('_', ' ')}</span>
                        </div>
                        <p className="text-xs text-[#CCC] mt-1.5">{ann.content}</p>
                        <button data-testid={`shared-seek-${ann.id}`} onClick={() => seekTo(ann.timestamp)}
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
  }

  // Folder listing view
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Play size={32} weight="fill" className="text-[#007AFF]" />
            <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>SOCCER SCOUT</h1>
          </div>
          <span className="text-xs text-[#666] bg-white/5 px-3 py-1.5 uppercase tracking-wider">
            Shared by {folderData.owner.name}
          </span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-8">
          <p className="text-xs text-[#A3A3A3] uppercase tracking-[0.2em] mb-2">Shared Folder</p>
          <h2 className="text-4xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{folderData.folder.name}</h2>
          <p className="text-[#A3A3A3] mt-1">{folderData.matches.length} match{folderData.matches.length !== 1 ? 'es' : ''}</p>
        </div>

        {folderData.matches.length === 0 ? (
          <div className="text-center py-20">
            <VideoCamera size={80} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-xl text-[#A3A3A3]">No matches in this folder yet</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {folderData.matches.map(match => (
              <div key={match.id} data-testid={`shared-match-card-${match.id}`}
                onClick={() => openMatch(match.id)}
                className="bg-[#141414] border border-white/10 p-6 hover:bg-[#1F1F1F] transition-colors cursor-pointer">
                <div className="flex items-center gap-2 mb-4">
                  <Trophy size={20} className="text-[#007AFF]" />
                  <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{match.competition || 'Friendly'}</p>
                </div>
                <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                  {match.team_home} vs {match.team_away}
                </h3>
                <div className="flex items-center gap-2 text-sm text-[#A3A3A3]">
                  <CalendarBlank size={16} />
                  <span>{new Date(match.date).toLocaleDateString()}</span>
                </div>
                {match.video_id && (
                  <div className="mt-4">
                    {match.processing_status === 'completed' ? (
                      <div className="flex items-center gap-2 text-[#4ADE80] text-sm">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        <span>Analysis Available</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 text-[#39FF14] text-sm">
                        <VideoCamera size={16} />
                        <span>Video available</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      <footer className="border-t border-white/5 px-6 py-4 text-center">
        <p className="text-xs text-[#555]">
          Powered by <span className="text-[#007AFF]">Soccer Scout</span> — AI-Powered Match Analysis
        </p>
      </footer>
    </div>
  );
};

export default SharedView;
