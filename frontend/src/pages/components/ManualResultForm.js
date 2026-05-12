import { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { Trophy, Plus, Trash, Check, ClipboardText, X } from '@phosphor-icons/react';
import ManualResultSummary from './ManualResultSummary';
import { useScrollIntoViewOnOpen } from '../../hooks/useScrollIntoViewOnOpen';

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

  // iter57: auto-scroll the editor into view when the user clicks "Edit"
  // (or first-time-entry). Fixes the silent-no-feedback UX on mobile where
  // the form opens below the fold and the page doesn't move.
  const editorRef = useScrollIntoViewOnOpen(editing);
  const [finishing, setFinishing] = useState(false);
  const [aiSummary, setAiSummary] = useState(null);
  const [shareRecapOpen, setShareRecapOpen] = useState(false);
  const [recapShareToken, setRecapShareToken] = useState(null);

  // Pre-bucket players by their `team` field so the per-event Player dropdown
  // doesn't re-filter the full roster on every keystroke / render.
  const playersByTeam = useMemo(() => {
    const buckets = { all: players || [] };
    for (const p of (players || [])) {
      const key = p.team || '__none__';
      buckets[key] = buckets[key] || [];
      buckets[key].push(p);
    }
    return buckets;
  }, [players]);
  const playersForEvent = (eventTeam) => (eventTeam ? (playersByTeam[eventTeam] || []) : playersByTeam.all);

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
    } catch (err) {
      // Expected: 404 when there's no manual_result yet — quietly ignore.
      // Surface anything else for debuggability.
      if (err.response?.status !== 404) {
        console.warn('[manual-result] could not preload existing result:', err);
      }
    }
    // Load any existing AI summary so we don't re-generate on every page load
    if (match.insights?.summary) setAiSummary(match.insights.summary);
    // Track pre-existing share token so the Share button reflects current state
    if (match.manual_result?.recap_share_token) {
      setRecapShareToken(match.manual_result.recap_share_token);
    }
  }, [match.id, match.insights?.summary, match.manual_result?.recap_share_token]);

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

  // Summary view (result already saved, not currently editing) — delegated to
  // ManualResultSummary so this file can stay focused on the editor.
  if (existing && !editing) {
    return (
      <ManualResultSummary
        match={match} existing={existing} players={players}
        aiSummary={aiSummary} finishing={finishing} error={error}
        recapShareToken={recapShareToken} shareRecapOpen={shareRecapOpen}
        onEdit={() => setEditing(true)}
        onFinish={handleFinish}
        onUnlock={handleUnlock}
        onDelete={handleDelete}
        onOpenShareRecap={() => setShareRecapOpen(true)}
        onCloseShareRecap={() => setShareRecapOpen(false)}
        onRecapTokenChange={setRecapShareToken}
      />
    );
  }

  // Editor (or first-time entry)
  return (
    <div ref={editorRef} data-testid="manual-result-form" className="bg-[#141414] border border-[#60A5FA]/30 p-4 sm:p-6 mb-6">
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
                {/* Mobile: full-width stacked, larger tap targets. Desktop: 12-col compact row. */}
                <div className="grid grid-cols-2 sm:grid-cols-12 gap-2">
                  <input type="number" inputMode="numeric" min="0" max="200" value={ev.minute}
                    onChange={(e) => updateEvent(i, { minute: e.target.value })}
                    placeholder="Min" aria-label="Minute"
                    className="col-span-1 sm:col-span-1 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-3 sm:py-2 text-sm sm:text-xs focus:border-[#60A5FA] focus:outline-none" />
                  <select value={ev.type} onChange={(e) => updateEvent(i, { type: e.target.value })} aria-label="Event type"
                    className="col-span-1 sm:col-span-2 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-3 sm:py-2 text-sm sm:text-xs focus:border-[#60A5FA] focus:outline-none">
                    {EVENT_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                  <select value={ev.team} onChange={(e) => updateEvent(i, { team: e.target.value })} aria-label="Team"
                    className="col-span-2 sm:col-span-3 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-3 sm:py-2 text-sm sm:text-xs focus:border-[#60A5FA] focus:outline-none">
                    <option value="">Team...</option>
                    <option value={match.team_home}>{match.team_home}</option>
                    <option value={match.team_away}>{match.team_away}</option>
                  </select>
                  <select value={ev.player_id || ''} onChange={(e) => updateEvent(i, { player_id: e.target.value })} aria-label="Player"
                    className="col-span-2 sm:col-span-2 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-3 sm:py-2 text-sm sm:text-xs focus:border-[#60A5FA] focus:outline-none">
                    <option value="">Player (opt)</option>
                    {playersForEvent(ev.team).map((p) => (
                      <option key={p.id} value={p.id}>#{p.number ?? '?'} {p.name}</option>
                    ))}
                  </select>
                  <input type="text" maxLength="120" value={ev.description}
                    onChange={(e) => updateEvent(i, { description: e.target.value })}
                    placeholder="Description (optional)" aria-label="Description"
                    className="col-span-2 sm:col-span-3 min-w-0 bg-[#141414] border border-white/10 text-white px-2 py-3 sm:py-2 text-sm sm:text-xs focus:border-[#60A5FA] focus:outline-none" />
                  <button data-testid={`remove-event-${i}-btn`} type="button" onClick={() => removeEvent(i)}
                    aria-label="Remove event"
                    className="col-span-2 sm:col-span-1 flex items-center justify-center gap-1.5 py-2.5 sm:py-2 text-[11px] sm:text-[10px] uppercase tracking-wider text-[#A3A3A3] hover:text-[#EF4444] hover:bg-[#EF4444]/10 border border-white/10 sm:border-0">
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

      <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
        <button data-testid="save-manual-result-btn" onClick={handleSave} disabled={saving}
          className="flex items-center justify-center gap-2 px-5 py-3 sm:py-2.5 bg-[#60A5FA] hover:bg-[#3B82F6] disabled:opacity-50 text-white text-xs font-bold tracking-wider uppercase transition-colors">
          {saving ? 'Saving…' : <><Check size={14} weight="bold" /> Save Result</>}
        </button>
      </div>
    </div>
  );
};

export default ManualResultForm;
