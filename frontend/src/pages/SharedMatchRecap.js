import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Trophy, CalendarBlank, Star } from '@phosphor-icons/react';

const OUTCOME_META = {
  W: { label: 'WIN', color: '#10B981' },
  L: { label: 'LOSS', color: '#EF4444' },
  D: { label: 'DRAW', color: '#FBBF24' },
};

const SharedMatchRecap = () => {
  const { shareToken } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/match-recap/public/${shareToken}`)
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch((err) => {
        if (!cancelled) setError(err.response?.status === 404 ? 'Recap not available' : 'Failed to load');
      });
    return () => { cancelled = true; };
  }, [shareToken]);

  if (error) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center px-6">
        <div className="text-center" data-testid="recap-error">
          <p className="text-2xl text-white mb-2" style={{ fontFamily: 'Bebas Neue' }}>{error}</p>
          <p className="text-sm text-[#A3A3A3]">The coach may have revoked this share link.</p>
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

  const outcome = OUTCOME_META[data.outcome] || OUTCOME_META.D;
  const goals = (data.key_events || []).filter((e) => (e.type || '').toLowerCase() === 'goal');

  return (
    <div className="min-h-screen bg-[#0A0A0A]" data-testid="shared-match-recap">
      <header className="border-b border-white/10 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <img src="/logo-mark-96.png" alt="Soccer Scout 11" className="h-8 w-auto" />
          <span className="text-xs tracking-[0.2em] uppercase text-[#A3A3A3] font-bold">Match Recap</span>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-6">
        <div className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border-l-4 p-6 sm:p-8"
          style={{ borderLeftColor: outcome.color }}>
          <div className="text-[10px] tracking-[0.2em] uppercase font-bold mb-3" style={{ color: outcome.color }}>
            {data.competition || 'Match Recap'}
          </div>
          <h1 className="text-3xl sm:text-5xl font-bold text-white mb-4 leading-tight" style={{ fontFamily: 'Bebas Neue' }}>
            {data.team_home} vs {data.team_away}
          </h1>
          <div className="flex items-baseline gap-4 mb-3">
            <span className="text-6xl sm:text-7xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>
              {data.home_score} – {data.away_score}
            </span>
            <span className="text-sm font-bold tracking-[0.2em] uppercase px-3 py-1.5"
              style={{ color: '#000', backgroundColor: outcome.color }} data-testid="recap-outcome-chip">
              {outcome.label}
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs text-[#A3A3A3] flex-wrap">
            {data.date && (
              <span className="flex items-center gap-1.5">
                <CalendarBlank size={14} /> {new Date(data.date + 'T00:00:00').toLocaleDateString()}
              </span>
            )}
            {data.coach_name && <span>· Coach {data.coach_name}</span>}
          </div>
        </div>

        {data.summary && (
          <div data-testid="recap-summary"
            className="bg-gradient-to-br from-[#1B0F2E] to-[#0A0A0A] border border-[#A855F7]/30 p-6">
            <div className="flex items-center gap-2 mb-3">
              <Star size={16} weight="fill" className="text-[#A855F7]" />
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A855F7]">AI Match Recap</span>
            </div>
            <p className="text-base sm:text-lg text-[#E5E5E5] leading-relaxed whitespace-pre-wrap">
              {data.summary}
            </p>
          </div>
        )}

        {goals.length > 0 && (
          <div data-testid="recap-goals" className="bg-[#141414] border border-white/10 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Trophy size={16} weight="fill" className="text-[#10B981]" />
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A3A3A3]">Goal Timeline</span>
            </div>
            <ul className="space-y-2">
              {goals.map((g, idx) => (
                <li key={idx} className="flex items-center gap-3 text-sm text-white">
                  <span className="text-[#10B981] font-bold w-12 text-right tabular-nums" style={{ fontFamily: 'Bebas Neue' }}>
                    {g.minute || 0}'
                  </span>
                  <span className="flex-1">{g.team}</span>
                  {g.description && <span className="text-xs text-[#A3A3A3] truncate max-w-[60%]">{g.description}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="text-center text-[10px] tracking-[0.2em] uppercase text-[#666] pt-6">
          Powered by Soccer Scout 11 · AI-Generated Recap
        </div>
      </main>
    </div>
  );
};

export default SharedMatchRecap;
