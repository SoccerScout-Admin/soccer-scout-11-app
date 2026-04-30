import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Sparkle, ArrowsClockwise, TrendUp, TrendDown, ChartLineUp, Trophy, Warning, Target } from '@phosphor-icons/react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const RESULT_COLOR = { W: '#10B981', D: '#FBBF24', L: '#EF4444' };

const SeasonTrends = () => {
  const { folderId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/folders/${folderId}/season-trends`, { headers: getAuthHeader() })
      .then(res => setData(res.data))
      .catch(() => { /* not generated yet */ })
      .finally(() => setLoading(false));
  }, [folderId]);

  const handleGenerate = async () => {
    setGenerating(true); setError(null);
    try {
      const res = await axios.post(`${API}/folders/${folderId}/season-trends`, {}, { headers: getAuthHeader() });
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to generate trends');
    } finally {
      setGenerating(false);
    }
  };

  const chartData = useMemo(() => {
    if (!data?.per_match) return [];
    return data.per_match.map((m, i) => ({
      name: `M${i + 1}`,
      label: `${m.team_home} vs ${m.team_away} (${m.date})`,
      goals_for: m.goals_for,
      goals_against: m.goals_against,
      result: m.result,
    }));
  }, [data]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#A855F7] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="season-trends">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => navigate('/')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <div>
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7]">Season Trends</div>
            <h1 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
              {data?.folder?.name || 'Season'}
            </h1>
          </div>
          <button data-testid="regenerate-btn" onClick={handleGenerate} disabled={generating}
            className="ml-auto flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-[#A855F7] to-[#FBBF24] hover:opacity-90 disabled:opacity-50 text-black text-xs font-bold tracking-wider uppercase rounded transition-opacity">
            {generating ? (
              <><div className="w-3 h-3 border-2 border-black border-t-transparent rounded-full animate-spin" /> Analyzing…</>
            ) : data ? (
              <><ArrowsClockwise size={14} weight="bold" /> Regenerate</>
            ) : (
              <><Sparkle size={14} weight="fill" /> Generate Trends</>
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
            <ChartLineUp size={56} weight="fill" className="text-[#A855F7] mx-auto mb-4" />
            <h2 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Discover Your Season Story</h2>
            <p className="text-sm text-[#A3A3A3] max-w-md mx-auto leading-relaxed">
              Aggregate every match in this folder into a single dashboard — record, goals chart,
              recurring patterns, and an AI-synthesised season verdict.
            </p>
            <p className="text-[11px] text-[#666] mt-4">Tip: generate match-level Insights first to unlock recurring-pattern analysis.</p>
          </div>
        )}

        {generating && !data && (
          <div className="text-center py-20">
            <div className="w-12 h-12 border-2 border-[#A855F7] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-sm text-[#A3A3A3]">Synthesizing the season…</p>
          </div>
        )}

        {data && (
          <>
            {/* Hero record + totals */}
            <section className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="record-grid">
              <div className="bg-[#0F1A14] border border-[#10B981]/30 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#10B981]">Wins</div>
                <div className="text-5xl font-bold text-[#10B981] mt-1" style={{ fontFamily: 'Bebas Neue' }}>{data.record.wins}</div>
              </div>
              <div className="bg-[#1F1A0E] border border-[#FBBF24]/30 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#FBBF24]">Draws</div>
                <div className="text-5xl font-bold text-[#FBBF24] mt-1" style={{ fontFamily: 'Bebas Neue' }}>{data.record.draws}</div>
              </div>
              <div className="bg-[#1F0E0E] border border-[#EF4444]/30 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#EF4444]">Losses</div>
                <div className="text-5xl font-bold text-[#EF4444] mt-1" style={{ fontFamily: 'Bebas Neue' }}>{data.record.losses}</div>
              </div>
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">GF / GA</div>
                <div className="text-3xl font-bold text-white mt-1" style={{ fontFamily: 'Bebas Neue' }}>
                  {data.totals.goals_for} <span className="text-[#666] text-xl">:</span> {data.totals.goals_against}
                </div>
              </div>
              <div className="bg-[#141414] border border-white/10 p-4">
                <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3]">Goal Diff</div>
                <div className={`text-3xl font-bold mt-1 ${data.totals.goal_difference >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]'}`} style={{ fontFamily: 'Bebas Neue' }}>
                  {data.totals.goal_difference > 0 ? '+' : ''}{data.totals.goal_difference}
                </div>
              </div>
            </section>

            {/* Goals chart */}
            {chartData.length > 0 && (
              <section data-testid="goals-chart">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-1 h-5 bg-[#007AFF]" />
                  <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Goals Per Match</h2>
                </div>
                <div className="bg-[#141414] border border-white/10 p-4 h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1F1F1F" />
                      <XAxis dataKey="name" tick={{ fill: '#A3A3A3', fontSize: 11 }} />
                      <YAxis tick={{ fill: '#A3A3A3', fontSize: 11 }} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ background: '#0A0A0A', border: '1px solid #333', borderRadius: 4 }}
                        labelFormatter={(v, payload) => payload?.[0]?.payload?.label || v}
                      />
                      <Legend wrapperStyle={{ fontSize: 11, color: '#A3A3A3' }} />
                      <Bar dataKey="goals_for" name="Goals For" fill="#10B981" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="goals_against" name="Goals Against" fill="#EF4444" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            {/* Season verdict */}
            {data.season_verdict && (
              <section data-testid="season-verdict"
                className="bg-gradient-to-br from-[#1B0F2E] to-[#141414] border border-[#A855F7]/30 p-6">
                <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7] mb-2">Season Verdict</div>
                <p className="text-xl leading-relaxed text-white" style={{ fontFamily: 'Bebas Neue' }}>
                  {data.season_verdict.verdict}
                </p>
                {data.season_verdict.trends?.length > 0 && (
                  <div className="mt-5">
                    <div className="text-xs tracking-wider uppercase text-[#A855F7] mb-2">Patterns Emerging</div>
                    <ul className="space-y-1.5 text-sm">
                      {data.season_verdict.trends.map((t, i) => (
                        <li key={`trend-${i}-${t?.slice?.(0, 32) || ''}`} className="text-[#E5E5E5]">• {t}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {data.season_verdict.focus_for_training?.length > 0 && (
                  <div className="mt-5">
                    <div className="text-xs tracking-wider uppercase text-[#FBBF24] mb-2">Focus For Training</div>
                    <ul className="space-y-1.5 text-sm">
                      {data.season_verdict.focus_for_training.map((f, i) => (
                        <li key={`focus-${i}-${f?.slice?.(0, 32) || ''}`} className="text-[#E5E5E5]">→ {f}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}

            {/* Recurring patterns */}
            <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div data-testid="strengths-card" className="bg-[#0F1A14] border border-[#10B981]/20 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <TrendUp size={18} weight="bold" className="text-[#10B981]" />
                  <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#10B981]">Recurring Strengths</h3>
                </div>
                {data.recurring_strengths.length === 0 ? (
                  <p className="text-xs text-[#666]">Generate insights on individual matches to unlock pattern detection.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.recurring_strengths.map((s, i) => (
                      <li key={`strength-${s.text?.slice?.(0, 48) || i}`} className="text-white flex justify-between gap-2">
                        <span className="flex-1">{s.text}</span>
                        <span className="text-[10px] text-[#10B981] tracking-wider uppercase font-bold">{s.count}x</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div data-testid="weaknesses-card" className="bg-[#1F0E0E] border border-[#EF4444]/20 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <TrendDown size={18} weight="bold" className="text-[#EF4444]" />
                  <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#EF4444]">Recurring Weaknesses</h3>
                </div>
                {data.recurring_weaknesses.length === 0 ? (
                  <p className="text-xs text-[#666]">Generate insights on individual matches to unlock pattern detection.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.recurring_weaknesses.map((w, i) => (
                      <li key={`weakness-${w.text?.slice?.(0, 48) || i}`} className="text-white flex justify-between gap-2">
                        <span className="flex-1">{w.text}</span>
                        <span className="text-[10px] text-[#EF4444] tracking-wider uppercase font-bold">{w.count}x</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>

            {/* Match-by-match timeline */}
            <section data-testid="match-timeline">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-1 h-5 bg-[#007AFF]" />
                <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Match-by-Match</h2>
              </div>
              <div className="space-y-2">
                {data.per_match.map((m, i) => (
                  <Link key={m.match_id} to={`/match/${m.match_id}`}
                    data-testid={`match-row-${m.match_id}`}
                    className="bg-[#141414] border border-white/10 hover:border-[#007AFF]/40 p-4 flex items-center gap-4 transition-colors">
                    <span className="text-2xl font-bold text-[#666] flex-shrink-0 min-w-[40px]" style={{ fontFamily: 'Bebas Neue' }}>
                      M{String(i + 1).padStart(2, '0')}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-white truncate">
                        {m.team_home} <span className="text-[#666] mx-2">vs</span> {m.team_away}
                      </div>
                      <div className="text-[10px] text-[#666] tracking-wider uppercase mt-0.5">
                        {m.date} {m.competition && `• ${m.competition}`}
                        {m.has_insights && <span className="text-[#A855F7]"> • AI insights ready</span>}
                      </div>
                      {m.summary && <p className="text-xs text-[#A3A3A3] mt-1 truncate italic">{m.summary}</p>}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <div className="text-2xl font-bold tracking-wider" style={{ fontFamily: 'Bebas Neue' }}>
                        {m.goals_for} <span className="text-[#333]">-</span> {m.goals_against}
                      </div>
                      <div className="w-7 h-7 rounded font-bold flex items-center justify-center text-xs"
                        style={{ backgroundColor: `${RESULT_COLOR[m.result]}25`, color: RESULT_COLOR[m.result] }}>
                        {m.result}
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </section>

            <p className="text-[10px] text-[#444] tracking-wider text-right">
              Generated {new Date(data.generated_at).toLocaleString()}
              {data.totals.matches_with_insights > 0 && (
                <> • {data.totals.matches_with_insights}/{data.totals.matches} matches contributed AI insights</>
              )}
            </p>
          </>
        )}
      </main>
    </div>
  );
};

export default SeasonTrends;
