import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { Trophy, Plus, Trash, Check, ClipboardText, PencilSimple, X } from '@phosphor-icons/react';

const EVENT_TYPES = [
  { key: 'goal', label: 'Goal', color: '#10B981' },
  { key: 'shot', label: 'Shot', color: '#60A5FA' },
  { key: 'save', label: 'Save', color: '#A855F7' },
  { key: 'foul', label: 'Foul', color: '#FBBF24' },
  { key: 'card', label: 'Card', color: '#EF4444' },
  { key: 'sub', label: 'Sub', color: '#A3A3A3' },
  { key: 'note', label: 'Note', color: '#CCCCCC' },
];

/**
 * Card for matches without uploaded video — lets the coach record the
 * scoreline, key events, and notes so the game counts toward season trends.
 */
const ManualResultForm = ({ match, players, onSaved }) => {
  const [existing, setExisting] = useState(null);
  const [editing, setEditing] = useState(false);
  const [homeScore, setHomeScore] = useState(0);
  const [awayScore, setAwayScore] = useState(0);
  const [notes, setNotes] = useState('');
  const [events, setEvents] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [quickGoalFlash, setQuickGoalFlash] = useState(null);
  const [finishing, setFinishing] = useState(false);
  const [aiSummary, setAiSummary] = useState(null);

  /**
   * Live-match logging helper: a single tap on the Home/Away Goal buttons bumps
   * the scoreline AND appends a `goal` event at the current wall-clock minute of
   * the match (computed from `match.date` + current time, clamped 0–120).
   * The minute and player can be edited afterward in the event row.
   */
  const _quickGoalMinute = () => {
    // Prefer the match.date as kickoff marker (00:00 local) — not precise but good enough.
    // If the match is from a past day, just use 45' as a reasonable mid-match default.
    const kickoffMs = match.date ? new Date(match.date + 'T15:00:00').getTime() : Date.now();
    const diffMin = Math.round((Date.now() - kickoffMs) / 60000);
    if (diffMin < 0 || diffMin > 120) return 0;
    return diffMin;
  };

  const handleQuickGoal = (side) => {
    const team = side === 'home' ? match.team_home : match.team_away;
    const minute = _quickGoalMinute();
    if (side === 'home') {
      setHomeScore((v) => Math.min(99, Number(v) + 1));
    } else {
      setAwayScore((v) => Math.min(99, Number(v) + 1));
    }
    setEvents((prev) => [...prev, { type: 'goal', minute, team, player_id: '', description: '' }]);
    setQuickGoalFlash(`+1 goal · ${team} · ${minute}'`);
    setTimeout(() => setQuickGoalFlash(null), 1800);
  };

  const loadExisting = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/matches/${match.id}/manual-result`, { headers: getAuthHeader() });
      if (res.data && Object.keys(res.data).length > 0) {
        setExisting(res.data);
        setHomeScore(res.data.home_score ?? 0);
        setAwayScore(res.data.away_score ?? 0);
        setNotes(res.data.notes || '');
        setEvents(res.data.key_events || []);
      } else {
        setExisting(null);
      }
    } catch { /* 404 = none yet */ }
    // Load any existing AI summary so we don't re-generate on every page load
    if (match.insights?.summary) setAiSummary(match.insights.summary);
  }, [match.id, match.insights?.summary]);

  useEffect(() => { loadExisting(); }, [loadExisting]);

  const addEvent = () => {
    setEvents((prev) => [...prev, { type: 'goal', minute: 0, team: match.team_home, player_id: '', description: '' }]);
  };

  const updateEvent = (idx, patch) => {
    setEvents((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)));
  };

  const removeEvent = (idx) => {
    setEvents((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await axios.put(`${API}/matches/${match.id}/manual-result`, {
        home_score: Number(homeScore) || 0,
        away_score: Number(awayScore) || 0,
        key_events: events.map((e) => ({
          type: e.type,
          minute: Number(e.minute) || 0,
          team: e.team || '',
          player_id: e.player_id || null,
          description: e.description || '',
        })),
        notes: notes.slice(0, 2000),
      }, { headers: getAuthHeader() });
      setExisting(res.data.manual_result);
      setEditing(false);
      if (onSaved) onSaved(res.data.manual_result);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save result');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Remove this manual result? Season stats will no longer include this match.')) return;
    try {
      await axios.delete(`${API}/matches/${match.id}/manual-result`, { headers: getAuthHeader() });
      setExisting(null);
      setHomeScore(0); setAwayScore(0); setNotes(''); setEvents([]);
      setEditing(false);
      setAiSummary(null);
      if (onSaved) onSaved(null);
    } catch (err) {
      alert('Failed to delete: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleFinish = async () => {
    if (!existing) return;
    setFinishing(true);
    setError(null);
    try {
      const res = await axios.post(`${API}/matches/${match.id}/finish`, {}, { headers: getAuthHeader() });
      setAiSummary(res.data.summary);
      setExisting((prev) => ({ ...(prev || {}), is_final: true, finished_at: res.data.finished_at }));
      if (onSaved) onSaved({ ...(existing || {}), is_final: true });
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to finish match');
    } finally {
      setFinishing(false);
    }
  };

  const handleUnlock = async () => {
    if (!window.confirm('Unlock this match? You can re-edit the score and events. The AI recap stays saved.')) return;
    try {
      await axios.post(`${API}/matches/${match.id}/unlock`, {}, { headers: getAuthHeader() });
      setExisting((prev) => {
        const next = { ...(prev || {}) };
        delete next.is_final;
        delete next.finished_at;
        return next;
      });
    } catch (err) {
      alert('Failed to unlock: ' + (err.response?.data?.detail || err.message));
    }
  };

  // Summary view (result already saved, not currently editing)
  if (existing && !editing) {
    const outcome = existing.outcome;
    const outcomeColor = outcome === 'W' ? '#10B981' : outcome === 'L' ? '#EF4444' : '#FBBF24';
    const isLocked = !!existing.is_final;
    return (
      <div data-testid="manual-result-summary" className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-[#60A5FA]/30 p-6 mb-6">
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <Trophy size={22} weight="fill" className="text-[#60A5FA]" />
            <div>
              <div className="text-[10px] tracking-[0.2em] uppercase text-[#60A5FA] flex items-center gap-2">
                <span>Manual Result — No Video</span>
                {isLocked && (
                  <span data-testid="match-locked-chip"
                    className="text-[9px] tracking-[0.2em] uppercase font-bold px-1.5 py-0.5 bg-[#10B981]/15 text-[#10B981] border border-[#10B981]/30">
                    Final
                  </span>
                )}
              </div>
              <div className="text-xs text-[#A3A3A3] mt-0.5">
                {isLocked ? 'Locked — final whistle blown' : 'Counted in season trends'}
              </div>
            </div>
          </div>
          <div className="flex gap-2 flex-wrap">
            {!isLocked && (
              <button data-testid="edit-manual-result-btn" onClick={() => setEditing(true)}
                className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors">
                <PencilSimple size={14} weight="bold" /> Edit
              </button>
            )}
            {!isLocked && (
              <button data-testid="finish-match-btn" onClick={handleFinish} disabled={finishing}
                className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 bg-gradient-to-r from-[#10B981] to-[#059669] text-white hover:opacity-90 transition-opacity disabled:opacity-50">
                {finishing ? (
                  <><div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" /> Generating recap…</>
                ) : (
                  <><Check size={14} weight="bold" /> Finish Match</>
                )}
              </button>
            )}
            {isLocked && (
              <button data-testid="unlock-match-btn" onClick={handleUnlock}
                className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 border border-[#FBBF24]/30 text-[#FBBF24] hover:bg-[#FBBF24]/10 transition-colors">
                <PencilSimple size={14} weight="bold" /> Unlock
              </button>
            )}
            <button data-testid="delete-manual-result-btn" onClick={handleDelete}
              disabled={isLocked}
              className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 border border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/15 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
              <Trash size={14} weight="bold" /> Remove
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 sm:gap-6 mb-4">
          <div className="flex-1 text-center min-w-0">
            <div className="text-[9px] sm:text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-1 truncate">{match.team_home}</div>
            <div className="text-4xl sm:text-5xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>{existing.home_score}</div>
          </div>
          <div className="flex items-center justify-center">
            <span className="px-2 sm:px-3 py-1 text-[10px] sm:text-xs font-bold tracking-[0.15em] sm:tracking-[0.2em] uppercase"
              style={{ color: outcomeColor, backgroundColor: `${outcomeColor}20`, border: `1px solid ${outcomeColor}40` }}>
              {outcome === 'W' ? 'Win' : outcome === 'L' ? 'Loss' : 'Draw'}
            </span>
          </div>
          <div className="flex-1 text-center min-w-0">
            <div className="text-[9px] sm:text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-1 truncate">{match.team_away}</div>
            <div className="text-4xl sm:text-5xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>{existing.away_score}</div>
          </div>
        </div>

        {existing.key_events?.length > 0 && (
          <div className="space-y-1.5 mt-4">
            <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-2">Key Events ({existing.key_events.length})</div>
            {existing.key_events.map((ev, i) => {
              const meta = EVENT_TYPES.find((t) => t.key === ev.type) || EVENT_TYPES[0];
              const player = ev.player_id ? players?.find((p) => p.id === ev.player_id) : null;
              return (
                <div key={`ev-${i}-${ev.minute}-${ev.type}`} data-testid={`manual-event-${i}`}
                  className="flex items-center gap-3 text-sm bg-[#0A0A0A] border border-white/5 px-3 py-2">
                  <span className="text-xs font-mono text-[#60A5FA] tabular-nums flex-shrink-0">{ev.minute}'</span>
                  <span className="text-[10px] font-bold tracking-wider uppercase px-1.5 py-0.5"
                    style={{ color: meta.color, backgroundColor: `${meta.color}20` }}>
                    {meta.label}
                  </span>
                  {ev.team && <span className="text-xs text-[#A3A3A3] truncate">{ev.team}</span>}
                  {player && <span className="text-xs text-[#FBBF24]">#{player.number || '?'} {player.name}</span>}
                  {ev.description && <span className="text-xs text-[#CCCCCC] truncate">{ev.description}</span>}
                </div>
              );
            })}
          </div>
        )}

        {existing.notes && (
          <div className="mt-4 bg-[#0A0A0A] border border-white/5 p-3">
            <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-1">Coach's Notes</div>
            <p className="text-sm text-[#E5E5E5] whitespace-pre-wrap leading-relaxed">{existing.notes}</p>
          </div>
        )}

        {aiSummary && (
          <div data-testid="ai-recap" className="mt-4 bg-gradient-to-br from-[#1B0F2E] to-[#0A0A0A] border border-[#A855F7]/30 p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-7 h-7 bg-[#A855F7]/15 border border-[#A855F7]/30 flex items-center justify-center flex-shrink-0">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#A855F7">
                  <path d="M12 2L9.91 8.26L2 9.27L7.91 14.14L6.18 22L12 18.27L17.82 22L16.09 14.14L22 9.27L14.09 8.26L12 2Z"/>
                </svg>
              </div>
              <div className="text-[10px] tracking-[0.2em] uppercase text-[#A855F7] font-bold">AI Match Recap</div>
            </div>
            <p className="text-sm text-[#E5E5E5] leading-relaxed whitespace-pre-wrap">{aiSummary}</p>
          </div>
        )}

        {error && (
          <div data-testid="finish-error" className="mt-3 text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 px-3 py-2">
            {error}
          </div>
        )}
      </div>
    );
  }

  // Editor (or first-time entry)
  return (
    <div data-testid="manual-result-form" className="bg-[#141414] border border-[#60A5FA]/30 p-6 mb-6">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <ClipboardText size={22} weight="bold" className="text-[#60A5FA]" />
          <div>
            <div className="text-lg font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
              {existing ? 'Edit Match Result' : 'Add Match Result Without Video'}
            </div>
            <div className="text-xs text-[#A3A3A3] mt-0.5">
              {existing ? 'Update scores, events or notes' : 'Record the scoreline so this game counts in season trends'}
            </div>
          </div>
        </div>
        {existing && (
          <button data-testid="cancel-manual-edit-btn" onClick={() => { setEditing(false); loadExisting(); }}
            className="p-2 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <X size={18} />
          </button>
        )}
      </div>

      {/* Scoreline — on mobile use big +/- steppers, on desktop keep the input field */}
      <div className="grid grid-cols-3 gap-3 sm:gap-4 items-end mb-5">
        <div className="text-center">
          <label className="block text-[9px] sm:text-[10px] tracking-[0.15em] sm:tracking-[0.2em] uppercase text-[#A3A3A3] mb-2 truncate">{match.team_home}</label>
          <div className="flex items-center gap-1 sm:block">
            <button type="button" data-testid="home-score-minus" onClick={() => setHomeScore((v) => Math.max(0, Number(v) - 1))}
              className="sm:hidden flex-shrink-0 w-10 h-14 bg-[#0A0A0A] border border-white/10 text-white text-xl font-bold hover:bg-[#1F1F1F] active:bg-[#2A2A2A]">−</button>
            <input data-testid="home-score-input" type="number" inputMode="numeric" pattern="[0-9]*" min="0" max="99" value={homeScore}
              onChange={(e) => setHomeScore(e.target.value)}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white text-3xl sm:text-4xl text-center font-bold py-3 focus:border-[#60A5FA] focus:outline-none"
              style={{ fontFamily: 'Bebas Neue' }} />
            <button type="button" data-testid="home-score-plus" onClick={() => setHomeScore((v) => Math.min(99, Number(v) + 1))}
              className="sm:hidden flex-shrink-0 w-10 h-14 bg-[#0A0A0A] border border-white/10 text-white text-xl font-bold hover:bg-[#1F1F1F] active:bg-[#2A2A2A]">+</button>
          </div>
        </div>
        <div className="text-center pb-3 text-[#666] text-2xl">–</div>
        <div className="text-center">
          <label className="block text-[9px] sm:text-[10px] tracking-[0.15em] sm:tracking-[0.2em] uppercase text-[#A3A3A3] mb-2 truncate">{match.team_away}</label>
          <div className="flex items-center gap-1 sm:block">
            <button type="button" data-testid="away-score-minus" onClick={() => setAwayScore((v) => Math.max(0, Number(v) - 1))}
              className="sm:hidden flex-shrink-0 w-10 h-14 bg-[#0A0A0A] border border-white/10 text-white text-xl font-bold hover:bg-[#1F1F1F] active:bg-[#2A2A2A]">−</button>
            <input data-testid="away-score-input" type="number" inputMode="numeric" pattern="[0-9]*" min="0" max="99" value={awayScore}
              onChange={(e) => setAwayScore(e.target.value)}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white text-3xl sm:text-4xl text-center font-bold py-3 focus:border-[#60A5FA] focus:outline-none"
              style={{ fontFamily: 'Bebas Neue' }} />
            <button type="button" data-testid="away-score-plus" onClick={() => setAwayScore((v) => Math.min(99, Number(v) + 1))}
              className="sm:hidden flex-shrink-0 w-10 h-14 bg-[#0A0A0A] border border-white/10 text-white text-xl font-bold hover:bg-[#1F1F1F] active:bg-[#2A2A2A]">+</button>
          </div>
        </div>
      </div>

      {/* Tap-to-add-goal — mobile-first live-match logging.
          Each tap bumps the scoreline AND inserts a goal event at the current minute (editable later). */}
      <div className="mb-5 grid grid-cols-2 gap-3" data-testid="quick-add-goals">
        <button type="button" data-testid="quick-add-home-goal" onClick={() => handleQuickGoal('home')}
          className="flex flex-col items-center gap-1 py-4 border-2 border-[#10B981]/30 bg-[#10B981]/5 hover:bg-[#10B981]/15 active:bg-[#10B981]/25 transition-colors">
          <div className="flex items-center gap-2">
            <Trophy size={18} weight="fill" className="text-[#10B981]" />
            <span className="text-xs font-bold tracking-[0.15em] uppercase text-[#10B981]">Goal</span>
          </div>
          <span className="text-[10px] text-[#A3A3A3] tracking-wider uppercase truncate px-2">{match.team_home}</span>
        </button>
        <button type="button" data-testid="quick-add-away-goal" onClick={() => handleQuickGoal('away')}
          className="flex flex-col items-center gap-1 py-4 border-2 border-[#EF4444]/30 bg-[#EF4444]/5 hover:bg-[#EF4444]/15 active:bg-[#EF4444]/25 transition-colors">
          <div className="flex items-center gap-2">
            <Trophy size={18} weight="fill" className="text-[#EF4444]" />
            <span className="text-xs font-bold tracking-[0.15em] uppercase text-[#EF4444]">Goal</span>
          </div>
          <span className="text-[10px] text-[#A3A3A3] tracking-wider uppercase truncate px-2">{match.team_away}</span>
        </button>
      </div>
      {quickGoalFlash && (
        <div data-testid="quick-goal-flash"
          className="mb-3 text-[10px] font-bold tracking-[0.2em] uppercase text-center py-1.5 bg-[#10B981]/10 text-[#10B981]">
          {quickGoalFlash}
        </div>
      )}

      {/* Key events */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <label className="text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3]">Key Events (optional)</label>
          <button data-testid="add-event-btn" type="button" onClick={addEvent}
            className="flex items-center gap-1.5 text-xs text-[#60A5FA] hover:text-white font-bold tracking-wider uppercase">
            <Plus size={12} weight="bold" /> Add Event
          </button>
        </div>
        {events.length === 0 ? (
          <p className="text-xs text-[#666] py-3 text-center border border-dashed border-white/5">No events added — optional.</p>
        ) : (
          <div className="space-y-2">
            {events.map((ev, i) => (
              <div key={`evform-${i}`} data-testid={`event-row-${i}`}
                className="bg-[#0A0A0A] border border-white/5 p-2.5 overflow-hidden">
                {/* Mobile: stacked 2x2 grid. Desktop: 12-col compact row. */}
                <div className="grid grid-cols-2 sm:grid-cols-12 gap-2">
                  <input type="number" inputMode="numeric" min="0" max="200" value={ev.minute}
                    onChange={(e) => updateEvent(i, { minute: e.target.value })}
                    placeholder="Min" aria-label="Minute"
                    className="col-span-1 sm:col-span-1 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-2 text-xs focus:border-[#60A5FA] focus:outline-none" />
                  <select value={ev.type} onChange={(e) => updateEvent(i, { type: e.target.value })} aria-label="Event type"
                    className="col-span-1 sm:col-span-2 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-2 text-xs focus:border-[#60A5FA] focus:outline-none">
                    {EVENT_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                  <select value={ev.team} onChange={(e) => updateEvent(i, { team: e.target.value })} aria-label="Team"
                    className="col-span-2 sm:col-span-3 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-2 text-xs focus:border-[#60A5FA] focus:outline-none">
                    <option value="">Team...</option>
                    <option value={match.team_home}>{match.team_home}</option>
                    <option value={match.team_away}>{match.team_away}</option>
                  </select>
                  <select value={ev.player_id || ''} onChange={(e) => updateEvent(i, { player_id: e.target.value })} aria-label="Player"
                    className="col-span-2 sm:col-span-2 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-2 text-xs focus:border-[#60A5FA] focus:outline-none">
                    <option value="">Player (opt)</option>
                    {(players || []).filter((p) => !ev.team || p.team === ev.team).map((p) => (
                      <option key={p.id} value={p.id}>#{p.number || '?'} {p.name}</option>
                    ))}
                  </select>
                  <input type="text" maxLength="120" value={ev.description}
                    onChange={(e) => updateEvent(i, { description: e.target.value })}
                    placeholder="Description" aria-label="Description"
                    className="col-span-2 sm:col-span-3 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-2 text-xs focus:border-[#60A5FA] focus:outline-none" />
                  <button data-testid={`remove-event-${i}-btn`} type="button" onClick={() => removeEvent(i)}
                    aria-label="Remove event"
                    className="col-span-2 sm:col-span-1 flex items-center justify-center gap-1.5 py-2 text-[10px] uppercase tracking-wider text-[#A3A3A3] hover:text-[#EF4444] hover:bg-[#EF4444]/10 border border-white/5 sm:border-0">
                    <Trash size={14} />
                    <span className="sm:hidden">Remove</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Notes */}
      <div className="mb-5">
        <label className="block text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Coach's Notes (optional)</label>
        <textarea data-testid="manual-notes-input" value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3} maxLength={2000}
          placeholder="How did the match go? Tactical takeaways, standout players, things to drill..."
          className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 text-sm resize-none focus:border-[#60A5FA] focus:outline-none" />
        <div className="text-[10px] text-[#555] text-right mt-1">{notes.length}/2000</div>
      </div>

      {error && <p data-testid="manual-error" className="text-xs text-[#EF4444] mb-3">{error}</p>}

      <div className="flex gap-2 justify-end">
        <button data-testid="save-manual-result-btn" onClick={handleSave} disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#60A5FA] hover:bg-[#3B82F6] disabled:opacity-50 text-white text-xs font-bold tracking-wider uppercase transition-colors">
          {saving ? 'Saving…' : <><Check size={14} weight="bold" /> Save Result</>}
        </button>
      </div>
    </div>
  );
};

export default ManualResultForm;
