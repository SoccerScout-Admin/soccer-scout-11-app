import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, UserCircle, CalendarBlank, Play, Trophy, FilmStrip, Shield, ShieldCheck, Warning } from '@phosphor-icons/react';

const STAT_ICON = {
  goal: { label: 'Goals', color: '#10B981', icon: Trophy },
  highlight: { label: 'Highlights', color: '#007AFF', icon: FilmStrip },
  save: { label: 'Saves', color: '#60A5FA', icon: ShieldCheck },
  foul: { label: 'Fouls', color: '#EF4444', icon: Warning },
  card: { label: 'Cards', color: '#FBBF24', icon: Shield },
  shot: { label: 'Shots', color: '#A855F7', icon: Play },
  chance: { label: 'Chances', color: '#F472B6', icon: Play },
};

const PlayerProfile = () => {
  const { playerId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/players/${playerId}/profile`, { headers: getAuthHeader() })
      .then(res => setData(res.data))
      .catch(err => console.error('Failed to fetch profile:', err))
      .finally(() => setLoading(false));
  }, [playerId]);

  const teamsBySeason = useMemo(() => {
    if (!data?.teams) return {};
    const map = {};
    for (const t of data.teams) {
      (map[t.season] ||= []).push(t);
    }
    return map;
  }, [data]);

  const seasons = useMemo(() =>
    Object.keys(teamsBySeason).sort((a, b) => b.localeCompare(a)),
    [teamsBySeason]
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white flex items-center justify-center">
        <p>Player not found</p>
      </div>
    );
  }

  const { player, stats, clips } = data;

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="player-profile">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => navigate(-1)}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <h1 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
            Player Profile
          </h1>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-10">
        {/* Hero */}
        <section className="flex items-center gap-6 bg-[#141414] border border-white/10 p-6">
          <div className="w-28 h-28 flex-shrink-0 rounded-full bg-[#0A0A0A] border-2 border-[#007AFF]/30 overflow-hidden flex items-center justify-center">
            {player.profile_pic_url ? (
              <img src={`${API.replace('/api', '')}${player.profile_pic_url}?v=${player.id}`}
                alt={player.name} className="w-full h-full object-cover" />
            ) : (
              <UserCircle size={64} className="text-[#333]" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-3">
              <span className="text-6xl font-bold text-[#007AFF]" style={{ fontFamily: 'Bebas Neue' }}>
                {player.number ?? '—'}
              </span>
              <h2 className="text-4xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>{player.name}</h2>
            </div>
            <p className="text-sm text-[#A3A3A3] mt-1">
              {player.position || 'No position'}
              {data.teams.length > 0 && <> • on {data.teams.length} team{data.teams.length === 1 ? '' : 's'}</>}
            </p>
          </div>
        </section>

        {/* Stats */}
        <section data-testid="player-stats">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1 h-5 bg-[#007AFF]" />
            <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Career Stats (clip-derived)</h2>
          </div>
          {stats.total_clips === 0 ? (
            <p className="text-[#666] text-sm">No clips yet for this player. Tag them in clips during analysis to populate stats.</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
              <div data-testid="stat-total" className="bg-[#141414] border border-white/10 p-4">
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
                const meta = STAT_ICON[type] || { label: type, color: '#A3A3A3', icon: FilmStrip };
                const Icon = meta.icon;
                return (
                  <div key={type} data-testid={`stat-${type}`} className="bg-[#141414] border border-white/10 p-4">
                    <div className="flex items-center gap-1.5 text-xs tracking-wider uppercase" style={{ color: meta.color }}>
                      <Icon size={12} weight="bold" /> {meta.label}
                    </div>
                    <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue', color: meta.color }}>{count}</div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Teams across seasons */}
        {seasons.length > 0 && (
          <section data-testid="player-teams">
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
                    <span className="text-xs text-[#666]">{teamsBySeason[season].length} team{teamsBySeason[season].length === 1 ? '' : 's'}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {teamsBySeason[season].map(t => (
                      <button key={t.id} data-testid={`team-chip-${t.id}`}
                        onClick={() => navigate(`/team/${t.id}`)}
                        className="text-xs px-3 py-1.5 bg-[#007AFF]/10 text-[#007AFF] hover:bg-[#007AFF]/20 transition-colors">
                        {t.name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Highlight Reel */}
        {clips.length > 0 && (
          <section data-testid="player-highlights">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-1 h-5 bg-[#007AFF]" />
              <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Highlight Reel ({clips.length})</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {clips.map(c => {
                const meta = STAT_ICON[c.clip_type] || STAT_ICON.highlight;
                const Icon = meta.icon;
                return (
                  <div key={c.id} data-testid={`clip-${c.id}`}
                    onClick={() => c.video_id && navigate(`/video/${c.video_id}`)}
                    className="bg-[#141414] border border-white/10 hover:border-[#007AFF]/40 p-4 cursor-pointer transition-colors">
                    <div className="flex items-start gap-3">
                      <div className="w-12 h-12 flex-shrink-0 rounded flex items-center justify-center"
                        style={{ backgroundColor: `${meta.color}1a`, color: meta.color }}>
                        <Icon size={20} weight="bold" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-semibold truncate">{c.title || 'Untitled clip'}</h3>
                        {c.match && (
                          <p className="text-xs text-[#A3A3A3] mt-0.5 truncate">
                            {c.match.team_home} vs {c.match.team_away} • {c.match.date}
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
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </main>
    </div>
  );
};

export default PlayerProfile;
