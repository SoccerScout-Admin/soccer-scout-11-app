import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { UserCircle, CalendarBlank, Play, Trophy, FilmStrip, Shield, ShieldCheck, Warning, Copy, Check, X, Link as LinkIcon } from '@phosphor-icons/react';

const STAT_META = {
  goal: { label: 'Goals', color: '#10B981', icon: Trophy },
  highlight: { label: 'Highlights', color: '#007AFF', icon: FilmStrip },
  save: { label: 'Saves', color: '#60A5FA', icon: ShieldCheck },
  foul: { label: 'Fouls', color: '#EF4444', icon: Warning },
  card: { label: 'Cards', color: '#FBBF24', icon: Shield },
  shot: { label: 'Shots', color: '#A855F7', icon: Play },
  chance: { label: 'Chances', color: '#F472B6', icon: Play },
};

const SharedPlayerProfile = () => {
  const { shareToken } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [activeClip, setActiveClip] = useState(null);
  const [copied, setCopied] = useState(false);
  const videoRef = useRef(null);

  useEffect(() => {
    axios.get(`${API}/shared/player/${shareToken}`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.status === 404 ? 'notfound' : 'error'));
  }, [shareToken]);

  useEffect(() => {
    if (videoRef.current && activeClip) {
      videoRef.current.load();
      videoRef.current.play().catch(() => {});
    }
  }, [activeClip]);

  const teamsBySeason = useMemo(() => {
    if (!data?.teams) return {};
    const map = {};
    for (const t of data.teams) (map[t.season] ||= []).push(t);
    return map;
  }, [data]);

  const seasons = useMemo(() => Object.keys(teamsBySeason).sort((a, b) => b.localeCompare(a)), [teamsBySeason]);

  const formatTime = (s) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

  const handleCopy = async () => {
    const url = `${window.location.origin}/api/og/player/${shareToken}`;
    try { await navigator.clipboard.writeText(url); }
    catch {
      const ta = document.createElement('textarea');
      ta.value = url; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (error === 'notfound') {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white flex items-center justify-center px-6">
        <div className="text-center max-w-md">
          <LinkIcon size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Profile Unavailable</h1>
          <p className="text-[#A3A3A3]">This player profile link has been revoked or never existed.</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const { player, stats, clips, owner } = data;

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="shared-player-profile">
      {/* Header */}
      <header className="bg-[#0A0A0A] border-b border-white/10 px-6 py-4 sticky top-0 z-40">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-2 h-2 bg-[#007AFF] rounded-full" />
            <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#007AFF]">Player Dossier</span>
          </div>
          <button data-testid="copy-share-btn" onClick={handleCopy}
            className={`flex items-center gap-2 px-3 py-2 text-xs font-bold tracking-wider uppercase transition-colors ${
              copied ? 'bg-[#10B981]/20 text-[#10B981]' : 'bg-[#007AFF]/10 text-[#007AFF] hover:bg-[#007AFF]/20'
            }`}>
            {copied ? <><Check size={12} weight="bold" /> Copied</> : <><Copy size={12} weight="bold" /> Copy Link</>}
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-10 space-y-12">
        {/* Hero */}
        <section className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-white/10 p-8 flex items-center gap-8">
          <div className="w-32 h-32 lg:w-40 lg:h-40 flex-shrink-0 rounded-full bg-[#0A0A0A] border-2 border-[#007AFF]/40 overflow-hidden flex items-center justify-center">
            {player.profile_pic_url ? (
              <img src={`${API.replace('/api', '')}${player.profile_pic_url}`} alt={player.name}
                className="w-full h-full object-cover" />
            ) : (
              <UserCircle size={80} className="text-[#333]" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-3 flex-wrap">
              {player.number != null && (
                <span className="text-7xl lg:text-8xl font-bold text-[#007AFF]" style={{ fontFamily: 'Bebas Neue' }}>
                  {player.number}
                </span>
              )}
              <h1 className="text-4xl lg:text-5xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{player.name}</h1>
            </div>
            <div className="text-base text-[#A3A3A3] mt-2 flex flex-wrap items-center gap-3">
              {player.position && <span>{player.position}</span>}
              {player.position && data.teams.length > 0 && <span className="text-[#333]">•</span>}
              {data.teams.length > 0 && (
                <span>{data.teams.length} team{data.teams.length === 1 ? '' : 's'}</span>
              )}
            </div>
            <div className="text-xs text-[#666] mt-3">Shared by Coach {owner}</div>
          </div>
        </section>

        {/* Stats */}
        {stats.total_clips > 0 && (
          <section data-testid="public-stats">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-1 h-5 bg-[#007AFF]" />
              <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Career Stats</h2>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-xs text-[#A3A3A3] tracking-wider uppercase">Total Clips</div>
                <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue' }}>{stats.total_clips}</div>
              </div>
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-xs text-[#A3A3A3] tracking-wider uppercase">Total Time</div>
                <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue' }}>
                  {Math.floor(stats.total_seconds / 60)}m {Math.round(stats.total_seconds % 60)}s
                </div>
              </div>
              {Object.entries(stats.by_type).map(([type, count]) => {
                const meta = STAT_META[type] || { label: type, color: '#A3A3A3', icon: FilmStrip };
                const Icon = meta.icon;
                return (
                  <div key={type} className="bg-[#141414] border border-white/10 p-4">
                    <div className="flex items-center gap-1.5 text-xs tracking-wider uppercase" style={{ color: meta.color }}>
                      <Icon size={12} weight="bold" /> {meta.label}
                    </div>
                    <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue', color: meta.color }}>{count}</div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Teams */}
        {seasons.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-1 h-5 bg-[#007AFF]" />
              <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Team History</h2>
            </div>
            <div className="space-y-3">
              {seasons.map(season => (
                <div key={season} className="bg-[#141414] border border-white/10 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <CalendarBlank size={14} className="text-[#007AFF]" />
                    <span className="text-sm font-bold tracking-wider">{season}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {teamsBySeason[season].map(t => (
                      <span key={t.id} className="text-xs px-3 py-1.5 bg-[#007AFF]/10 text-[#007AFF]">{t.name}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Highlight Reel — clickable inline player */}
        {clips.length > 0 && (
          <section data-testid="public-highlights">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-1 h-5 bg-[#007AFF]" />
              <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Highlight Reel ({clips.length})</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {clips.map(c => {
                const meta = STAT_META[c.clip_type] || STAT_META.highlight;
                const Icon = meta.icon;
                return (
                  <button key={c.id} data-testid={`public-clip-${c.id}`}
                    onClick={() => setActiveClip(c)}
                    disabled={!c.share_token}
                    className="bg-[#141414] border border-white/10 hover:border-[#007AFF]/40 p-4 text-left transition-colors disabled:opacity-50">
                    <div className="flex items-start gap-3">
                      <div className="w-12 h-12 flex-shrink-0 rounded flex items-center justify-center"
                        style={{ backgroundColor: `${meta.color}1a`, color: meta.color }}>
                        <Icon size={20} weight="bold" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-semibold truncate">{c.title || 'Untitled clip'}</h3>
                        {c.match && (
                          <p className="text-xs text-[#A3A3A3] mt-0.5 truncate">
                            {c.match.team_home} vs {c.match.team_away}
                          </p>
                        )}
                        <div className="flex items-center gap-2 text-[10px] text-[#666] mt-1 tracking-wider uppercase">
                          <span>{c.clip_type}</span>
                          <span>•</span>
                          <span>{formatTime(c.end_time - c.start_time)}</span>
                          {c.auto_generated && <><span>•</span><span className="text-[#007AFF]">AI</span></>}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        <footer className="pt-8 mt-8 border-t border-white/5 text-center">
          <p className="text-xs text-[#444] tracking-wider">
            Powered by <span className="text-[#007AFF]">Soccer Scout</span>
          </p>
        </footer>
      </main>

      {/* Inline clip viewer modal */}
      {activeClip && (
        <div data-testid="clip-viewer-overlay" onClick={() => setActiveClip(null)}
          className="fixed inset-0 bg-black/85 z-[200] flex items-center justify-center p-4">
          <div onClick={(e) => e.stopPropagation()}
            className="bg-[#0A0A0A] border border-white/10 max-w-4xl w-full">
            <div className="flex items-start justify-between p-4 border-b border-white/10">
              <div className="min-w-0 flex-1">
                <h3 className="text-xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>{activeClip.title}</h3>
                {activeClip.match && (
                  <p className="text-xs text-[#A3A3A3] mt-1">
                    {activeClip.match.team_home} vs {activeClip.match.team_away} • {activeClip.clip_type}
                  </p>
                )}
              </div>
              <button data-testid="close-clip-viewer" onClick={() => setActiveClip(null)}
                className="p-2 text-[#666] hover:text-white">
                <X size={20} />
              </button>
            </div>
            <video ref={videoRef} key={activeClip.id} autoPlay controls
              className="w-full aspect-video bg-black"
              src={`${API}/shared/clip/${activeClip.share_token}/video`}
              preload="auto" />
          </div>
        </div>
      )}
    </div>
  );
};

export default SharedPlayerProfile;
