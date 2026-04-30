import { useState, useEffect } from 'react';
import axios from 'axios';
import { API } from '../../App';
import { Star, CaretRight } from '@phosphor-icons/react';

const OUTCOME_COLOR = { W: '#10B981', L: '#EF4444', D: '#FBBF24' };

const GameOfTheWeekBanner = () => {
  const [gotw, setGotw] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/game-of-the-week`)
      .then((res) => { if (!cancelled && res.data.active) setGotw(res.data); })
      .catch(() => { /* silent */ });
    return () => { cancelled = true; };
  }, []);

  if (!gotw) return null;
  const accent = OUTCOME_COLOR[gotw.outcome] || '#FBBF24';
  const publicUrl = `/match-recap/${gotw.share_token}`;

  return (
    <a data-testid="gotw-dashboard-banner" href={publicUrl} target="_blank" rel="noopener noreferrer"
      className="group block mb-6 relative overflow-hidden bg-gradient-to-r from-[#1B0F2E] via-[#221640] to-[#0F1A2E] border-l-4 hover:border-l-[6px] transition-all"
      style={{ borderLeftColor: accent }}>
      <div className="absolute inset-y-0 right-0 w-24 opacity-10 flex items-center justify-center">
        <Star size={96} weight="fill" className="text-[#FBBF24]" />
      </div>
      <div className="relative p-5 flex items-center gap-4">
        <div className="w-10 h-10 bg-[#FBBF24]/15 border border-[#FBBF24]/30 flex items-center justify-center flex-shrink-0">
          <Star size={18} weight="fill" className="text-[#FBBF24]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[9px] tracking-[0.3em] uppercase font-bold text-[#FBBF24]">Game of the Week</span>
            <span className="text-[9px] text-[#A3A3A3] tracking-wider uppercase">· {gotw.days_remaining}d left</span>
          </div>
          <div className="text-lg sm:text-xl font-bold text-white truncate" style={{ fontFamily: 'Bebas Neue' }}>
            {gotw.team_home} {gotw.home_score}–{gotw.away_score} {gotw.team_away}
          </div>
          {gotw.summary && (
            <p className="text-xs text-[#D5D5D5] mt-1 line-clamp-1">{gotw.summary}</p>
          )}
        </div>
        <CaretRight size={20} className="text-[#FBBF24] group-hover:translate-x-1 transition-transform flex-shrink-0" />
      </div>
    </a>
  );
};

export default GameOfTheWeekBanner;
