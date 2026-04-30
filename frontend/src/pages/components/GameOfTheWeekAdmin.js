import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { Star, X, CalendarBlank } from '@phosphor-icons/react';

const GameOfTheWeekAdmin = () => {
  const [active, setActive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tokenInput, setTokenInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/game-of-the-week`);
      setActive(res.data.active ? res.data : null);
    } catch (err) {
      console.error('[gotw] fetch failed', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const _promote = async () => {
    const token = tokenInput.trim().split('/').pop();
    if (!token) { setError('Paste a share link or token'); return; }
    setBusy(true); setError(null);
    try {
      await axios.post(`${API}/admin/game-of-the-week/set`, { share_token: token }, { headers: getAuthHeader() });
      setTokenInput('');
      await fetch();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to set');
    } finally { setBusy(false); }
  };

  const _clear = async () => {
    if (!window.confirm('Clear the current Game of the Week now?')) return;
    setBusy(true);
    try {
      await axios.delete(`${API}/admin/game-of-the-week`, { headers: getAuthHeader() });
      await fetch();
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="gotw-admin-card"
      className="bg-gradient-to-r from-[#1B0F2E] via-[#141414] to-[#0F1A2E] border border-[#FBBF24]/30 p-5 mb-6">
      <div className="flex items-center gap-2 mb-4">
        <Star size={18} weight="fill" className="text-[#FBBF24]" />
        <h3 className="text-sm font-bold tracking-[0.2em] uppercase text-white">Game of the Week</h3>
        {active && (
          <span className="text-[9px] tracking-[0.2em] uppercase font-bold px-2 py-0.5 bg-[#FBBF24]/15 text-[#FBBF24] border border-[#FBBF24]/30">
            Live · {active.days_remaining}d left
          </span>
        )}
      </div>

      {loading ? (
        <p className="text-xs text-[#666]">Loading…</p>
      ) : active ? (
        <div data-testid="gotw-current" className="bg-[#0A0A0A] border border-white/5 p-4 mb-3">
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="flex-1 min-w-0">
              <div className="text-xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>
                {active.team_home} {active.home_score}–{active.away_score} {active.team_away}
              </div>
              <div className="text-[10px] text-[#A3A3A3] mt-1 flex items-center gap-2 flex-wrap">
                {active.competition && <span>{active.competition}</span>}
                {active.date && <span className="flex items-center gap-1"><CalendarBlank size={10} /> {active.date}</span>}
                {active.featured_by_name && <span>· picked by {active.featured_by_name}</span>}
              </div>
            </div>
            <button data-testid="gotw-clear-btn" onClick={_clear} disabled={busy}
              className="flex items-center gap-1 text-[10px] font-bold tracking-wider uppercase px-2 py-1 border border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10 disabled:opacity-50">
              <X size={12} /> Clear
            </button>
          </div>
          {active.summary && (
            <p className="text-[11px] text-[#D5D5D5] leading-relaxed line-clamp-2">{active.summary}</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-[#A3A3A3] mb-3 leading-relaxed">
          Paste a share link (or token) from any finished match recap. It'll appear as a banner on every coach's dashboard for 7 days, then auto-expire.
        </p>
      )}

      <div className="flex gap-2">
        <input data-testid="gotw-token-input" type="text" value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="https://.../match-recap/token_or_just_token"
          className="flex-1 bg-[#0A0A0A] border border-white/10 text-white text-xs px-3 py-2 focus:outline-none focus:border-[#FBBF24]" />
        <button data-testid="gotw-promote-btn" onClick={_promote} disabled={busy || !tokenInput.trim()}
          className="text-[10px] font-bold tracking-wider uppercase px-3 py-2 bg-[#FBBF24]/15 text-[#FBBF24] border border-[#FBBF24]/30 hover:bg-[#FBBF24]/25 disabled:opacity-50">
          {busy ? 'Working…' : (active ? 'Replace' : 'Promote')}
        </button>
      </div>
      {error && <div className="mt-2 text-[10px] text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 px-2 py-1">{error}</div>}
    </div>
  );
};

export default GameOfTheWeekAdmin;
