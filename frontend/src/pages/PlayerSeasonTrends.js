import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Sparkle, ArrowsClockwise, UserCircle, TrendUp, Target, GraduationCap, Lightbulb, Star, Globe } from '@phosphor-icons/react';

const LEVEL_COLORS = {
  'Pro Academy': '#A855F7',
  'College D1': '#60A5FA',
  'College D3/D2': '#10B981',
  'High School Varsity': '#FBBF24',
  'Youth Competitive': '#F472B6',
  'Youth Recreational': '#A3A3A3',
};

const PlayerSeasonTrends = () => {
  const { playerId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [teamId, setTeamId] = useState(null);
  const [availableTeams, setAvailableTeams] = useState([]);
  const [networkBenchmarks, setNetworkBenchmarks] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        // Resolve teams the player is on so the coach can pick context
        const profile = await axios.get(`${API}/players/${playerId}/profile`, { headers: getAuthHeader() });
        setAvailableTeams(profile.data.teams || []);
        if (!teamId && profile.data.teams?.length) {
          setTeamId(profile.data.teams[0].id);
        }
        // Try to load cached trends
        try {
          const params = teamId ? { team_id: teamId } : {};
          const res = await axios.get(`${API}/players/${playerId}/season-trends`, { headers: getAuthHeader(), params });
          setData(res.data);
        } catch { /* not generated yet */ }
        // Coach Network benchmarks (best-effort)
        try {
          const bench = await axios.get(`${API}/coach-network/benchmarks`, { headers: getAuthHeader() });
          if (bench.data?.ready) setNetworkBenchmarks(bench.data);
        } catch { /* not enough coaches */ }
      } catch {
        setError('Player not found');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [playerId, teamId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerate = async () => {
    setGenerating(true); setError(null);
    try {
      const params = teamId ? { team_id: teamId } : {};
      const res = await axios.post(`${API}/players/${playerId}/season-trends`, {}, { headers: getAuthHeader(), params });
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to generate trends');
    } finally {
      setGenerating(false);
    }
  };

  const formatTime = (s) => `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#A855F7] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="player-season-trends">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => navigate(`/player/${playerId}`)}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7]">Player Season Trends</div>
            <h1 className="text-2xl font-bold tracking-wider uppercase truncate" style={{ fontFamily: 'Bebas Neue' }}>
              {data?.player?.name || 'Player'}
            </h1>
          </div>
          {availableTeams.length > 1 && (
            <select data-testid="team-context-select"
              value={teamId || ''} onChange={e => setTeamId(e.target.value)}
              className="bg-[#0A0A0A] border border-white/10 text-xs text-[#A3A3A3] px-3 py-2 focus:outline-none">
              {availableTeams.map(t => (
                <option key={t.id} value={t.id}>{t.name} • {t.season}</option>
              ))}
            </select>
          )}
          <button data-testid="regenerate-btn" onClick={handleGenerate} disabled={generating}
            className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-[#A855F7] to-[#FBBF24] hover:opacity-90 disabled:opacity-50 text-black text-xs font-bold tracking-wider uppercase rounded transition-opacity">
            {generating ? (
              <><div className="w-3 h-3 border-2 border-black border-t-transparent rounded-full animate-spin" /> Analyzing…</>
            ) : data ? (
              <><ArrowsClockwise size={14} weight="bold" /> Regenerate</>
            ) : (
              <><Sparkle size={14} weight="fill" /> Generate Report</>
            )}
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-10 space-y-10">
        {error && (
          <div className="bg-[#1F0E0E] border border-[#EF4444]/30 p-4 text-sm text-[#EF4444]">{error}</div>
        )}

        {!data && !generating && (
          <div data-testid="trends-empty" className="text-center py-20 border border-dashed border-white/10">
            <Sparkle size={56} weight="fill" className="text-[#A855F7] mx-auto mb-4" />
            <h2 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Recruiter-Grade Season Report</h2>
            <p className="text-sm text-[#A3A3A3] max-w-lg mx-auto leading-relaxed">
              Aggregate every clip tagged with this player into a season-level report:
              role on the current team, position-specific scout attributes, recruiter-readiness score,
              and tailored development priorities.
            </p>
            <p className="text-[11px] text-[#666] mt-4">Tip: tag this player on individual clips first to populate the report.</p>
          </div>
        )}

        {generating && !data && (
          <div className="text-center py-20">
            <div className="w-12 h-12 border-2 border-[#A855F7] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-sm text-[#A3A3A3]">Synthesizing the season…</p>
          </div>
        )}

        {data && data.report && (
          <>
            {/* Player hero */}
            <section className="bg-gradient-to-br from-[#1B0F2E] to-[#141414] border border-[#A855F7]/30 p-6 flex items-center gap-6">
              <div className="w-24 h-24 flex-shrink-0 rounded-full bg-[#0A0A0A] border-2 border-[#A855F7]/40 overflow-hidden flex items-center justify-center">
                {data.player.profile_pic_url ? (
                  <img src={`${API.replace('/api', '')}${data.player.profile_pic_url}?v=${data.player.id}`} alt={data.player.name}
                    className="w-full h-full object-cover" />
                ) : (
                  <UserCircle size={56} className="text-[#333]" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-3 flex-wrap">
                  {data.player.number != null && (
                    <span className="text-5xl font-bold text-[#A855F7]" style={{ fontFamily: 'Bebas Neue' }}>
                      #{data.player.number}
                    </span>
                  )}
                  <h2 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{data.player.name}</h2>
                </div>
                <p className="text-sm text-[#A3A3A3] mt-1">
                  {data.rubric.label} • {data.team.name} • {data.team.season}
                </p>
                <p className="text-xl text-white mt-3 leading-relaxed" style={{ fontFamily: 'Bebas Neue' }}>
                  {data.report.player_summary}
                </p>
              </div>
            </section>

            {/* Stats overview */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">Total Clips</div>
                <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue' }}>{data.stats.total_clips}</div>
              </div>
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">Featured Time</div>
                <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue' }}>{formatTime(data.stats.total_seconds)}</div>
              </div>
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">Matches Active</div>
                <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue' }}>{data.per_match.length}</div>
              </div>
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">Position</div>
                <div className="text-xl font-bold mt-2" style={{ fontFamily: 'Bebas Neue' }}>{data.player.position || 'N/A'}</div>
              </div>
            </section>

            {/* Team Role */}
            <section data-testid="team-role-card"
              className="bg-[#141414] border border-white/10 p-6">
              <div className="flex items-center gap-2 mb-3">
                <Target size={18} weight="bold" className="text-[#007AFF]" />
                <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Role on {data.team.name}</h2>
              </div>
              <p className="text-sm text-white mb-5 italic">{data.report.team_role.current_role}</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-[#0F1A14] border border-[#10B981]/20 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <TrendUp size={14} weight="bold" className="text-[#10B981]" />
                    <h3 className="text-xs font-bold tracking-wider uppercase text-[#10B981]">Strengths for the team</h3>
                  </div>
                  <ul className="space-y-2 text-sm text-white">
                    {data.report.team_role.strengths_for_team.map((s, i) => (
                      <li key={i} className="flex gap-2"><span className="text-[#10B981] flex-shrink-0">+</span><span>{s}</span></li>
                    ))}
                  </ul>
                </div>
                <div className="bg-[#1F1A0E] border border-[#FBBF24]/20 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Lightbulb size={14} weight="bold" className="text-[#FBBF24]" />
                    <h3 className="text-xs font-bold tracking-wider uppercase text-[#FBBF24]">Opportunities for the team</h3>
                  </div>
                  <ul className="space-y-2 text-sm text-white">
                    {data.report.team_role.opportunities_for_team.map((o, i) => (
                      <li key={i} className="flex gap-2"><span className="text-[#FBBF24] flex-shrink-0">→</span><span>{o}</span></li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            {/* Recruiter View */}
            <section data-testid="recruiter-card"
              className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-[#60A5FA]/30 p-6">
              <div className="flex items-center gap-2 mb-5">
                <GraduationCap size={20} weight="bold" className="text-[#60A5FA]" />
                <h2 className="text-xs font-bold tracking-[0.2em] uppercase text-[#60A5FA]">Recruiter Lens — {data.rubric.label}</h2>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                <div className="md:col-span-1 bg-[#0A0A0A] border p-5"
                  style={{ borderColor: `${LEVEL_COLORS[data.report.recruiter_view.estimated_level] || '#60A5FA'}40` }}>
                  <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">Suggested Level</div>
                  <div className="text-xl font-bold mt-1" style={{
                    fontFamily: 'Bebas Neue',
                    color: LEVEL_COLORS[data.report.recruiter_view.estimated_level] || '#60A5FA',
                  }}>
                    {data.report.recruiter_view.estimated_level}
                  </div>
                  <div className="mt-4 flex items-center gap-1">
                    {[...Array(10)].map((_, i) => (
                      <Star key={i} size={14} weight={i < Math.round(data.report.recruiter_view.scout_score) ? 'fill' : 'regular'}
                        className={i < Math.round(data.report.recruiter_view.scout_score) ? 'text-[#FBBF24]' : 'text-[#333]'} />
                    ))}
                  </div>
                  <div className="text-3xl font-bold text-[#FBBF24] mt-1" style={{ fontFamily: 'Bebas Neue' }}>
                    {data.report.recruiter_view.scout_score}<span className="text-base text-[#666]"> / 10</span>
                  </div>
                  <p className="text-[11px] text-[#A3A3A3] mt-2 leading-relaxed">{data.report.recruiter_view.scout_score_rationale}</p>
                  {networkBenchmarks?.recruit_level_distribution && (() => {
                    const myLevel = data.report.recruiter_view.estimated_level;
                    const totalRated = networkBenchmarks.recruit_level_distribution.reduce((sum, r) => sum + r.count, 0);
                    const myCount = networkBenchmarks.recruit_level_distribution.find((r) => r.level === myLevel)?.count || 0;
                    if (totalRated < 3 || myCount === 0) return null;
                    const pct = Math.round((myCount / totalRated) * 100);
                    return (
                      <div data-testid="platform-percentile-chip"
                        className="mt-3 flex items-center gap-1.5 text-[10px] text-[#A855F7] bg-[#A855F7]/10 border border-[#A855F7]/30 px-2 py-1.5 rounded">
                        <Globe size={11} weight="bold" />
                        <span>{pct}% of platform-rated players land at <strong>{myLevel}</strong> ({myCount}/{totalRated})</span>
                      </div>
                    );
                  })()}
                </div>

                <div className="md:col-span-2 bg-[#0A0A0A] border border-white/10 p-5">
                  <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-3">Scout Attributes</div>
                  <div className="space-y-3">
                    {data.report.recruiter_view.scout_attributes.map((a, i) => (
                      <div key={i} data-testid={`attribute-${i}`}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-semibold text-white">{a.attribute}</span>
                          <span className="text-xs text-[#FBBF24] font-bold tracking-wider">{a.rating}/10</span>
                        </div>
                        <div className="h-1.5 bg-[#1F1F1F] rounded overflow-hidden">
                          <div className="h-full transition-all rounded"
                            style={{
                              width: `${a.rating * 10}%`,
                              background: a.rating >= 7 ? '#10B981' : a.rating >= 5 ? '#FBBF24' : '#EF4444',
                            }} />
                        </div>
                        {a.notes && <p className="text-[10px] text-[#666] mt-1 italic">{a.notes}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-[#0F1A14] border border-[#10B981]/20 p-4">
                  <h3 className="text-xs font-bold tracking-wider uppercase text-[#10B981] mb-2">Where they excel</h3>
                  <ul className="space-y-2 text-sm text-white">
                    {data.report.recruiter_view.where_they_excel.map((e, i) => (
                      <li key={i} className="flex gap-2"><span className="text-[#10B981] flex-shrink-0">★</span><span>{e}</span></li>
                    ))}
                  </ul>
                </div>
                <div className="bg-[#1F0E0E] border border-[#EF4444]/20 p-4">
                  <h3 className="text-xs font-bold tracking-wider uppercase text-[#EF4444] mb-2">Development priorities</h3>
                  <ul className="space-y-2 text-sm text-white">
                    {data.report.recruiter_view.development_priorities.map((d, i) => (
                      <li key={i} className="flex gap-2"><span className="text-[#EF4444] flex-shrink-0">!</span><span>{d}</span></li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            {/* Next-Level Checklist */}
            {data.report.next_level_checklist?.milestones?.length > 0 && (
              <section data-testid="next-level-card"
                className="bg-gradient-to-br from-[#0F1F1A] to-[#141414] border border-[#10B981]/30 p-6">
                <div className="flex items-center gap-2 mb-2">
                  <Target size={18} weight="bold" className="text-[#10B981]" />
                  <h2 className="text-xs font-bold tracking-[0.2em] uppercase text-[#10B981]">
                    Path to {data.report.next_level_checklist.next_level}
                  </h2>
                </div>
                <p className="text-xs text-[#A3A3A3] mb-5">
                  Specific milestones this player must hit to reach the next recruitment tier — ordered from easiest to hardest.
                </p>
                <div className="space-y-3">
                  {data.report.next_level_checklist.milestones.map((m, i) => (
                    <div key={i} data-testid={`milestone-${i}`}
                      className="bg-[#0A0A0A] border border-white/10 p-4 flex items-start gap-4">
                      <div className="w-8 h-8 rounded-full bg-[#10B981]/15 border border-[#10B981]/30 flex items-center justify-center flex-shrink-0">
                        <span className="text-sm font-bold text-[#10B981]" style={{ fontFamily: 'Bebas Neue' }}>{i + 1}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-semibold text-white">{m.milestone}</h3>
                        {m.why_it_matters && (
                          <p className="text-[11px] text-[#A3A3A3] mt-1.5">
                            <span className="text-[#60A5FA] font-bold tracking-wider uppercase mr-1.5">Why</span>
                            {m.why_it_matters}
                          </p>
                        )}
                        {m.how_to_train && (
                          <p className="text-[11px] text-[#A3A3A3] mt-1">
                            <span className="text-[#FBBF24] font-bold tracking-wider uppercase mr-1.5">Drill</span>
                            {m.how_to_train}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Recommended Drills */}
            {data.report.recommended_drills?.length > 0 && (
              <section data-testid="drills-card">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-1 h-5 bg-[#FBBF24]" />
                  <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Recommended Drills</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {data.report.recommended_drills.map((d, i) => (
                    <div key={i} data-testid={`drill-${i}`}
                      className="bg-[#141414] border border-white/10 p-4 flex items-start gap-3 hover:border-[#FBBF24]/40 transition-colors">
                      <span className="text-2xl font-bold text-[#FBBF24] flex-shrink-0" style={{ fontFamily: 'Bebas Neue' }}>
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <p className="text-sm text-white pt-1">{d}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <p className="text-[10px] text-[#444] tracking-wider text-right">
              Generated {new Date(data.generated_at).toLocaleString()} • gemini-2.5-flash
            </p>
          </>
        )}
      </main>
    </div>
  );
};

export default PlayerSeasonTrends;
