import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Sparkle, ArrowsClockwise, TrendUp, TrendDown, Trophy, Lightbulb, Clock, Warning, Globe } from '@phosphor-icons/react';
import SpokenSummaryPanel from './components/SpokenSummaryPanel';

// Common soccer-domain stop-words that would inflate fuzzy matches across very different statements.
const STOP_WORDS = new Set([
  'team', 'teams', 'play', 'plays', 'played', 'playing', 'game', 'games', 'goal', 'goals',
  'minute', 'minutes', 'match', 'matches', 'with', 'from', 'this', 'that', 'their', 'there',
  'were', 'where', 'which', 'what', 'when', 'into', 'about', 'half', 'time', 'around',
]);

// Loose fuzzy match — checks if both phrases share ≥2 meaningful words (length>=4, non-stop-words).
const fuzzyMatchPattern = (text, pattern) => {
  const norm = (s) => (s || '').toLowerCase().replace(/[^a-z\s]/g, ' ');
  const filterMeaningful = (arr) => arr.filter((w) => w.length >= 4 && !STOP_WORDS.has(w));
  const a = filterMeaningful(norm(text).split(/\s+/));
  const b = filterMeaningful(norm(pattern).split(/\s+/));
  if (a.length === 0 || b.length === 0) return false;
  const overlap = a.filter((w) => b.includes(w)).length;
  return overlap >= 2;
};

const NetworkChip = ({ count, kind }) => (
  <span data-testid={`network-chip-${kind}`}
    className="inline-flex items-center gap-1 ml-2 px-1.5 py-0.5 text-[9px] font-bold tracking-wider uppercase bg-[#A855F7]/15 text-[#A855F7] border border-[#A855F7]/30">
    <Globe size={9} weight="bold" /> {count} coaches also
  </span>
);

const MatchInsights = () => {
  const { matchId } = useParams();
  const navigate = useNavigate();
  const [match, setMatch] = useState(null);
  const [insights, setInsights] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [networkBenchmarks, setNetworkBenchmarks] = useState(null);
  const [voiceKeyMomentsCount, setVoiceKeyMomentsCount] = useState(0);

  useEffect(() => {
    const load = async () => {
      try {
        const m = await axios.get(`${API}/matches/${matchId}`, { headers: getAuthHeader() });
        setMatch(m.data);
        try {
          const ins = await axios.get(`${API}/matches/${matchId}/insights`, { headers: getAuthHeader() });
          setInsights(ins.data);
        } catch { /* not generated yet */ }
        // Coach Network benchmarks (best-effort, may return ready=false)
        try {
          const bench = await axios.get(`${API}/coach-network/benchmarks`, { headers: getAuthHeader() });
          if (bench.data?.ready) setNetworkBenchmarks(bench.data);
        } catch { /* not enough coaches yet */ }
        // Count voice key_moments to enable/disable Auto-reel button
        try {
          if (m.data?.video_id) {
            const annsRes = await axios.get(`${API}/annotations/video/${m.data.video_id}`, { headers: getAuthHeader() });
            const voiceKM = (annsRes.data || []).filter(
              (a) => a.source === 'voice' && a.annotation_type === 'key_moment'
            ).length;
            setVoiceKeyMomentsCount(voiceKM);
          }
        } catch { /* noop */ }
      } catch (err) {
        setError('Match not found');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [matchId]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await axios.post(`${API}/matches/${matchId}/insights`, {}, { headers: getAuthHeader() });
      setInsights(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to generate insights');
    } finally {
      setGenerating(false);
    }
  };

  const formatTime = (s) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#A855F7] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white flex items-center justify-center px-6">
        <div className="text-center">
          <Warning size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <p className="text-[#A3A3A3]">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="match-insights">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => navigate(`/match/${matchId}`)}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <div>
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7]">Match Insights</div>
            <h1 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
              {match.team_home} vs {match.team_away}
            </h1>
          </div>
          <button data-testid="regenerate-btn" onClick={handleGenerate} disabled={generating}
            className="ml-auto flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-[#A855F7] to-[#FBBF24] hover:opacity-90 disabled:opacity-50 text-black text-xs font-bold tracking-wider uppercase rounded transition-opacity">
            {generating ? (
              <><div className="w-3 h-3 border-2 border-black border-t-transparent rounded-full animate-spin" /> Generating…</>
            ) : insights ? (
              <><ArrowsClockwise size={14} weight="bold" /> Regenerate</>
            ) : (
              <><Sparkle size={14} weight="fill" /> Generate Insights</>
            )}
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10 space-y-10">
        <SpokenSummaryPanel
          matchId={matchId}
          hasVoiceKeyMoments={voiceKeyMomentsCount > 0}
          onSummaryUpdated={(newSummary) =>
            setInsights((prev) => prev ? { ...prev, summary: newSummary } : prev)
          }
        />

        {!insights && !generating && (
          <div data-testid="insights-empty" className="text-center py-20 border border-dashed border-white/10">
            <Sparkle size={56} weight="fill" className="text-[#A855F7] mx-auto mb-4" />
            <h2 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Ready for AI Analysis</h2>
            <p className="text-sm text-[#A3A3A3] max-w-md mx-auto leading-relaxed">
              Generate a coaching brief from this match's timeline markers — verdict, strengths, weaknesses,
              talking points for next training, and the most pivotal moments.
            </p>
          </div>
        )}

        {generating && !insights && (
          <div className="text-center py-20">
            <div className="w-12 h-12 border-2 border-[#A855F7] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-sm text-[#A3A3A3]">Analyzing your match film…</p>
          </div>
        )}

        {insights && (
          <>
            {/* Summary */}
            <section data-testid="summary-card"
              className="bg-gradient-to-br from-[#1B0F2E] to-[#141414] border border-[#A855F7]/30 p-6">
              <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7] mb-2">Verdict</div>
              <p className="text-2xl leading-relaxed text-white" style={{ fontFamily: 'Bebas Neue' }}>
                {insights.summary}
              </p>
              {insights.score_context && (
                <p className="text-sm text-[#A3A3A3] mt-3 italic">{insights.score_context}</p>
              )}
            </section>

            {/* Strengths + Weaknesses */}
            <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div data-testid="strengths-card" className="bg-[#0F1A14] border border-[#10B981]/20 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <TrendUp size={18} weight="bold" className="text-[#10B981]" />
                  <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#10B981]">Strengths</h3>
                </div>
                <ul className="space-y-2 text-sm">
                  {insights.strengths.map((s, i) => {
                    const match = networkBenchmarks?.common_strengths_across_coaches?.find((n) => fuzzyMatchPattern(s, n.text));
                    return (
                      <li key={i} className="text-white leading-relaxed flex gap-2 flex-wrap">
                        <span className="text-[#10B981] flex-shrink-0">+</span>
                        <span className="flex-1">{s}{match && <NetworkChip count={match.count} kind={`strength-${i}`} />}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
              <div data-testid="weaknesses-card" className="bg-[#1F0E0E] border border-[#EF4444]/20 p-5">
                <div className="flex items-center gap-2 mb-3">
                  <TrendDown size={18} weight="bold" className="text-[#EF4444]" />
                  <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#EF4444]">Weaknesses</h3>
                </div>
                <ul className="space-y-2 text-sm">
                  {insights.weaknesses.map((w, i) => {
                    const match = networkBenchmarks?.common_weaknesses_across_coaches?.find((n) => fuzzyMatchPattern(w, n.text));
                    return (
                      <li key={i} className="text-white leading-relaxed flex gap-2 flex-wrap">
                        <span className="text-[#EF4444] flex-shrink-0">−</span>
                        <span className="flex-1">{w}{match && <NetworkChip count={match.count} kind={`weakness-${i}`} />}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </section>

            {/* Coaching points */}
            <section data-testid="coaching-card">
              <div className="flex items-center gap-2 mb-4">
                <Lightbulb size={18} weight="bold" className="text-[#FBBF24]" />
                <h3 className="text-xs font-bold tracking-[0.2em] uppercase">Coaching Points for Next Training</h3>
              </div>
              <div className="space-y-2">
                {insights.coaching_points.map((p, i) => (
                  <div key={i} data-testid={`coaching-${i}`}
                    className="bg-[#141414] border border-white/10 p-4 flex items-start gap-3">
                    <span className="text-2xl font-bold text-[#FBBF24] flex-shrink-0" style={{ fontFamily: 'Bebas Neue' }}>
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <p className="text-sm text-white leading-relaxed pt-1">{p}</p>
                  </div>
                ))}
              </div>
            </section>

            {/* Key moments */}
            {insights.key_moments?.length > 0 && (
              <section data-testid="moments-card">
                <div className="flex items-center gap-2 mb-4">
                  <Trophy size={18} weight="bold" className="text-[#007AFF]" />
                  <h3 className="text-xs font-bold tracking-[0.2em] uppercase">Pivotal Moments</h3>
                </div>
                <div className="space-y-2">
                  {insights.key_moments.map((m, i) => (
                    <div key={i} data-testid={`moment-${i}`}
                      className="bg-[#141414] border border-white/10 p-4 flex items-start gap-4 hover:border-[#007AFF]/40 transition-colors">
                      <div className="flex items-center gap-1.5 text-[#007AFF] font-bold tracking-wider text-sm flex-shrink-0">
                        <Clock size={14} weight="bold" />
                        {formatTime(m.time)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-[10px] text-[#666] tracking-wider uppercase mr-2">{m.type}</span>
                        <span className="text-sm text-white">{m.description}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <p className="text-[10px] text-[#444] tracking-wider text-right">
              Generated {new Date(insights.generated_at).toLocaleString()} • {insights.model}
            </p>
          </>
        )}
      </main>
    </div>
  );
};

export default MatchInsights;
