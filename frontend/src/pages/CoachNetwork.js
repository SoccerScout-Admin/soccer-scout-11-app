import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Globe, Users, Trophy, FilmStrip, ChartLineUp, Lock, GraduationCap } from '@phosphor-icons/react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, PieChart, Pie, Cell } from 'recharts';

const BUCKET_COLOR = {
  'Top 25%': '#10B981',
  'Top 50%': '#60A5FA',
  'Bottom 50%': '#FBBF24',
  'Bottom 25%': '#EF4444',
  '—': '#A3A3A3',
};

const LEVEL_COLOR = {
  'Pro Academy': '#A855F7',
  'College D1': '#60A5FA',
  'College D3/D2': '#10B981',
  'High School Varsity': '#FBBF24',
  'Youth Competitive': '#F472B6',
  'Youth Recreational': '#A3A3A3',
};

const CoachNetwork = () => {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/coach-network/benchmarks`, { headers: getAuthHeader() })
      .then(res => setData(res.data))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, []);

  const positionChart = useMemo(() => {
    if (!data?.position_breakdown) return [];
    return data.position_breakdown.map(p => ({ name: p.position.slice(0, 15), value: p.count }));
  }, [data]);

  const levelChart = useMemo(() => {
    if (!data?.recruit_level_distribution) return [];
    return data.recruit_level_distribution.map(l => ({
      name: l.level, value: l.count, color: LEVEL_COLOR[l.level] || '#A3A3A3',
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
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="coach-network">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => navigate('/')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <div>
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7]">Coach Network</div>
            <h1 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
              Platform Benchmarks
            </h1>
          </div>
          <div className="ml-auto flex items-center gap-2 text-xs text-[#666]">
            <Lock size={14} /> Anonymized
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-10 space-y-10">
        {/* Privacy explainer */}
        <section className="bg-[#0F1A2E] border border-[#60A5FA]/20 p-5 flex items-start gap-3">
          <Lock size={20} weight="bold" className="text-[#60A5FA] flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-bold tracking-wider uppercase text-[#60A5FA]">Privacy first</h3>
            <p className="text-xs text-[#A3A3A3] mt-1 leading-relaxed">
              All metrics on this page are aggregated anonymously across {data?.platform?.coaches || 0} coaches.
              Trend themes only surface when at least <strong className="text-white">{data?.k_anonymity_threshold || 3} coaches</strong> have
              hit the same pattern. No individual coach's data is ever exposed — including yours.
            </p>
          </div>
        </section>

        {!data?.ready && data?.message && (
          <div data-testid="not-ready"
            className="text-center py-20 border border-dashed border-white/10">
            <Globe size={56} weight="fill" className="text-[#A855F7] mx-auto mb-4" />
            <h2 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Almost There</h2>
            <p className="text-sm text-[#A3A3A3] max-w-md mx-auto leading-relaxed">{data.message}</p>
          </div>
        )}

        {data?.ready && (
          <>
            {/* Platform stats */}
            <section className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="platform-stats">
              {[
                { label: 'Coaches', val: data.platform.coaches, icon: Users, color: '#A855F7' },
                { label: 'Teams', val: data.platform.teams, icon: Trophy, color: '#60A5FA' },
                { label: 'Matches', val: data.platform.matches, icon: FilmStrip, color: '#10B981' },
                { label: 'Clips', val: data.platform.clips, icon: ChartLineUp, color: '#FBBF24' },
                { label: 'AI Markers', val: data.platform.markers, icon: ChartLineUp, color: '#F472B6' },
              ].map(s => {
                const Icon = s.icon;
                return (
                  <div key={s.label} className="bg-[#141414] border border-white/10 p-4">
                    <div className="flex items-center gap-1.5 text-[10px] tracking-wider uppercase" style={{ color: s.color }}>
                      <Icon size={12} weight="bold" /> {s.label}
                    </div>
                    <div className="text-3xl font-bold mt-1" style={{ fontFamily: 'Bebas Neue', color: s.color }}>
                      {s.val.toLocaleString()}
                    </div>
                  </div>
                );
              })}
            </section>

            {/* Your bucket on the network */}
            <section data-testid="your-bucket" className="bg-gradient-to-br from-[#1B0F2E] to-[#141414] border border-[#A855F7]/30 p-6">
              <div className="text-[10px] tracking-wider uppercase text-[#A855F7] mb-3">Your bucket on the platform</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-[#0A0A0A] border border-white/10 p-4">
                  <div className="text-xs text-[#A3A3A3] mb-1">Matches uploaded</div>
                  <div className="flex items-baseline gap-3">
                    <span className="text-4xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{data.you.matches}</span>
                    <span className="text-[10px] text-[#666] tracking-wider">avg {data.distributions.matches_per_coach.avg} • median {data.distributions.matches_per_coach.median}</span>
                  </div>
                  <div className="mt-2 inline-block text-[10px] font-bold tracking-wider uppercase px-2 py-1"
                    style={{ backgroundColor: `${BUCKET_COLOR[data.you.matches_bucket]}25`, color: BUCKET_COLOR[data.you.matches_bucket] }}>
                    {data.you.matches_bucket}
                  </div>
                </div>
                <div className="bg-[#0A0A0A] border border-white/10 p-4">
                  <div className="text-xs text-[#A3A3A3] mb-1">Clips created</div>
                  <div className="flex items-baseline gap-3">
                    <span className="text-4xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{data.you.clips}</span>
                    <span className="text-[10px] text-[#666] tracking-wider">avg {data.distributions.clips_per_coach.avg} • median {data.distributions.clips_per_coach.median}</span>
                  </div>
                  <div className="mt-2 inline-block text-[10px] font-bold tracking-wider uppercase px-2 py-1"
                    style={{ backgroundColor: `${BUCKET_COLOR[data.you.clips_bucket]}25`, color: BUCKET_COLOR[data.you.clips_bucket] }}>
                    {data.you.clips_bucket}
                  </div>
                </div>
              </div>
            </section>

            {/* Position distribution */}
            {positionChart.length > 0 && (
              <section data-testid="position-chart">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-1 h-5 bg-[#60A5FA]" />
                  <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Player Positions Across the Network</h2>
                </div>
                <div className="bg-[#141414] border border-white/10 p-4 h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={positionChart}>
                      <XAxis dataKey="name" tick={{ fill: '#A3A3A3', fontSize: 11 }} />
                      <YAxis tick={{ fill: '#A3A3A3', fontSize: 11 }} allowDecimals={false} />
                      <Tooltip contentStyle={{ background: '#0A0A0A', border: '1px solid #333' }} />
                      <Bar dataKey="value" name="Players" fill="#60A5FA" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            {/* Recruit level distribution */}
            {levelChart.length > 0 && (
              <section data-testid="level-chart">
                <div className="flex items-center gap-2 mb-4">
                  <GraduationCap size={18} weight="bold" className="text-[#A855F7]" />
                  <h2 className="text-xs font-bold tracking-[0.2em] uppercase">Recruiter-Level Distribution</h2>
                </div>
                <p className="text-xs text-[#A3A3A3] mb-3">
                  Where AI-evaluated players land across the platform (sample: {data.samples.player_trends_aggregated} reports).
                </p>
                <div className="bg-[#141414] border border-white/10 p-4 h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={levelChart} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label>
                        {levelChart.map((entry) => (
                          <Cell key={`lvl-${entry.name}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ background: '#0A0A0A', border: '1px solid #333' }} />
                      <Legend wrapperStyle={{ fontSize: 11, color: '#A3A3A3' }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </section>
            )}

            {/* Common patterns across coaches */}
            <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-[#0F1A14] border border-[#10B981]/20 p-5" data-testid="common-strengths">
                <h3 className="text-xs font-bold tracking-wider uppercase text-[#10B981] mb-3">
                  Top Strengths Across {data.samples.match_insights_aggregated} Match Reports
                </h3>
                {data.common_strengths_across_coaches.length === 0 ? (
                  <p className="text-xs text-[#666]">Not enough cross-coach data yet (need ≥{data.k_anonymity_threshold} coaches per theme).</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.common_strengths_across_coaches.map((s, i) => (
                      <li key={`cstr-${i}-${s.text?.slice?.(0, 32) || ''}`} className="text-white flex justify-between gap-2">
                        <span className="flex-1">{s.text}</span>
                        <span className="text-[10px] text-[#10B981] tracking-wider uppercase font-bold">{s.count} coaches</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="bg-[#1F0E0E] border border-[#EF4444]/20 p-5" data-testid="common-weaknesses">
                <h3 className="text-xs font-bold tracking-wider uppercase text-[#EF4444] mb-3">
                  Top Weaknesses Across {data.samples.match_insights_aggregated} Match Reports
                </h3>
                {data.common_weaknesses_across_coaches.length === 0 ? (
                  <p className="text-xs text-[#666]">Not enough cross-coach data yet (need ≥{data.k_anonymity_threshold} coaches per theme).</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.common_weaknesses_across_coaches.map((w, i) => (
                      <li key={`cwk-${i}-${w.text?.slice?.(0, 32) || ''}`} className="text-white flex justify-between gap-2">
                        <span className="flex-1">{w.text}</span>
                        <span className="text-[10px] text-[#EF4444] tracking-wider uppercase font-bold">{w.count} coaches</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>

            <p className="text-[10px] text-[#444] tracking-wider text-right">
              Updated {new Date(data.generated_at).toLocaleString()} • Aggregated across {data.platform.coaches} coaches
            </p>
          </>
        )}
      </main>
    </div>
  );
};

export default CoachNetwork;
