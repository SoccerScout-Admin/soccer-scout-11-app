import { useState, useEffect, useMemo } from 'react';
import { X, MagnifyingGlass, Check, Trash } from '@phosphor-icons/react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';

/**
 * iter102 — Tag Player Modal (Hudl-style manual attribution).
 *
 * Opens when the user clicks the small edit button on a markers panel row.
 * Shows the match roster filtered to the marker's team (with toggle to
 * "show all"), with search. Clicking a player calls PATCH /api/markers/{id}
 * and propagates the updated row back up via onMarkerUpdated.
 *
 * Also offers:
 *   - "Clear AI tag" → strips player_number + player_name
 *   - "Delete marker" → removes the row entirely (use when AI logged
 *     something that wasn't actually a real event)
 */

const TagPlayerModal = ({ marker, matchId, isOpen, onClose, onMarkerUpdated, onMarkerDeleted }) => {
  const [roster, setRoster] = useState([]);
  const [search, setSearch] = useState('');
  const [showAllTeams, setShowAllTeams] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen || !matchId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await axios.get(`${API}/players/match/${matchId}`, { headers: getAuthHeader() });
        if (!cancelled) setRoster(r.data || []);
      } catch (err) {
        if (!cancelled) setError('Could not load roster: ' + (err.response?.data?.detail || err.message));
      }
    })();
    return () => { cancelled = true; };
  }, [isOpen, matchId]);

  const filtered = useMemo(() => {
    let list = roster;
    if (!showAllTeams && marker?.team && marker.team !== 'neutral') {
      list = list.filter((p) => (p.team || '').toLowerCase() === marker.team.toLowerCase());
    }
    if (search.trim()) {
      const s = search.toLowerCase();
      list = list.filter((p) =>
        (p.name || '').toLowerCase().includes(s) ||
        String(p.number || '').includes(s) ||
        (p.position || '').toLowerCase().includes(s),
      );
    }
    return list.slice(0, 60); // safety cap so a 200-player roster doesn't lock up the DOM
  }, [roster, search, showAllTeams, marker]);

  if (!isOpen || !marker) return null;

  const callPatch = async (payload) => {
    setSaving(true);
    setError(null);
    try {
      const r = await axios.patch(`${API}/markers/${marker.id}`, payload, { headers: getAuthHeader() });
      onMarkerUpdated?.(r.data);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Update failed');
    } finally {
      setSaving(false);
    }
  };

  const handlePick = (player) => callPatch({
    player_number: player.number,
    player_name: player.name,
    team: player.team || marker.team,
  });

  const handleClear = () => callPatch({ clear_player: true });

  const handleDelete = async () => {
    if (!window.confirm('Delete this marker permanently?')) return;
    setSaving(true);
    setError(null);
    try {
      await axios.delete(`${API}/markers/${marker.id}`, { headers: getAuthHeader() });
      onMarkerDeleted?.(marker.id);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Delete failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      data-testid="tag-player-modal"
      className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-end sm:items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-[#141414] border border-white/10 w-full max-w-md max-h-[85vh] flex flex-col shadow-2xl">
        {/* Header */}
        <header className="flex items-center justify-between p-4 border-b border-white/10">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-[0.2em] text-[#FBBF24] font-bold mb-1">Tag Player</p>
            <p className="text-sm text-white truncate">{marker.label || marker.type}</p>
            <p className="text-[11px] text-[#666]">
              {Math.floor(marker.time / 60)}:{String(Math.floor(marker.time % 60)).padStart(2, '0')}
              {marker.team && marker.team !== 'neutral' && ` · ${marker.team}`}
            </p>
          </div>
          <button
            data-testid="tag-player-close"
            onClick={onClose}
            className="p-1.5 hover:bg-white/5 transition-colors flex-shrink-0"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </header>

        {/* Search */}
        <div className="p-3 border-b border-white/5">
          <div className="relative">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#666]" />
            <input
              data-testid="tag-player-search"
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, #, or position"
              className="w-full bg-[#0A0A0A] border border-white/10 pl-9 pr-3 py-2 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#FBBF24] transition-colors"
            />
          </div>
          {marker.team && marker.team !== 'neutral' && (
            <label className="flex items-center gap-2 mt-2 text-xs text-[#888] cursor-pointer">
              <input
                data-testid="tag-player-show-all-teams"
                type="checkbox"
                checked={showAllTeams}
                onChange={(e) => setShowAllTeams(e.target.checked)}
                className="accent-[#FBBF24]"
              />
              Show both teams
            </label>
          )}
        </div>

        {/* Roster list */}
        <div className="flex-1 overflow-y-auto divide-y divide-white/5 min-h-0">
          {filtered.length === 0 ? (
            <p className="text-xs text-[#666] p-6 text-center">
              {roster.length === 0
                ? 'No players in the roster yet. Open the Players tab to add some.'
                : 'No players match your search.'}
            </p>
          ) : (
            filtered.map((p) => {
              const isCurrent = marker.player_number === p.number && marker.player_name === p.name;
              return (
                <button
                  key={p.id}
                  data-testid={`tag-player-row-${p.id}`}
                  onClick={() => handlePick(p)}
                  disabled={saving}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.04] transition-colors text-left disabled:opacity-50"
                >
                  <div className="w-9 h-9 rounded-full border border-[#FBBF24]/40 text-[#FBBF24] flex items-center justify-center text-xs font-bold tabular-nums flex-shrink-0">
                    {p.number ?? '—'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{p.name}</p>
                    <p className="text-[11px] text-[#666] truncate">
                      {p.position || 'No position'}
                      {p.team && ` · ${p.team}`}
                    </p>
                  </div>
                  {isCurrent && <Check size={16} weight="bold" className="text-[#10B981] flex-shrink-0" />}
                </button>
              );
            })
          )}
        </div>

        {/* Footer actions */}
        <footer className="p-3 border-t border-white/10 flex items-center gap-2">
          {(marker.player_number || marker.player_name) && (
            <button
              data-testid="tag-player-clear-btn"
              onClick={handleClear}
              disabled={saving}
              className="text-xs uppercase tracking-wider text-[#A3A3A3] hover:text-white px-3 py-2 transition-colors disabled:opacity-50"
            >
              Clear AI tag
            </button>
          )}
          <button
            data-testid="tag-player-delete-btn"
            onClick={handleDelete}
            disabled={saving}
            className="ml-auto flex items-center gap-1.5 text-xs uppercase tracking-wider text-[#EF4444] hover:bg-[#EF4444]/10 px-3 py-2 transition-colors disabled:opacity-50"
          >
            <Trash size={13} weight="bold" />
            Delete marker
          </button>
        </footer>

        {error && (
          <p data-testid="tag-player-error" className="text-xs text-[#EF4444] px-4 py-2 bg-[#1A0A0A] border-t border-[#EF4444]/30">
            {error}
          </p>
        )}
      </div>
    </div>
  );
};

export default TagPlayerModal;
