import { useMemo, useState } from 'react';
import { SoccerBall, Target, Hand, Warning, Flag, ArrowsClockwise, Lightning, Eye, PencilSimple, CheckCircle } from '@phosphor-icons/react';
import TagPlayerModal from './TagPlayerModal';

/**
 * iter100 — Rich Markers Panel.
 *
 * A scannable list of every AI-generated timeline event. Each row shows
 * type icon + label + time chip + jersey-number avatar (iter99 attribution).
 * Click any row to seek the video to that moment.
 *
 * Filters by type so coaches can answer "show me all 3 goals" in one click.
 */

const TYPE_META = {
  goal:         { icon: SoccerBall,       color: '#FBBF24', label: 'Goals',         priority: 1 },
  shot:         { icon: Target,           color: '#EF4444', label: 'Shots',         priority: 2 },
  save:         { icon: Hand,             color: '#7DD3FC', label: 'Saves',         priority: 3 },
  chance:       { icon: Lightning,        color: '#A78BFA', label: 'Chances',       priority: 4 },
  foul:         { icon: Warning,          color: '#F97316', label: 'Fouls',         priority: 5 },
  card:         { icon: Flag,             color: '#DC2626', label: 'Cards',         priority: 6 },
  substitution: { icon: ArrowsClockwise,  color: '#10B981', label: 'Subs',          priority: 7 },
  tactical:     { icon: Eye,              color: '#6B7280', label: 'Tactical',      priority: 8 },
};

const ALL_FILTER = '__ALL__';

const formatTime = (s) => {
  const total = Math.floor(s || 0);
  const m = Math.floor(total / 60);
  const sec = total % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
};

const MarkerRow = ({ marker, onSeek, onEdit }) => {
  const meta = TYPE_META[marker.type] || TYPE_META.tactical;
  const Icon = meta.icon;
  const hasAttribution = !!marker.player_number || !!marker.player_name;
  return (
    <div
      data-testid={`marker-row-${marker.id}`}
      className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-white/[0.04] transition-colors border-l-2 group"
      style={{ borderLeftColor: meta.color }}
    >
      <button
        data-testid={`marker-row-seek-${marker.id}`}
        onClick={() => onSeek(marker.time)}
        className="flex items-center gap-3 flex-1 min-w-0 text-left"
      >
        <div
          className="w-7 h-7 flex items-center justify-center flex-shrink-0 rounded-sm"
          style={{ backgroundColor: `${meta.color}20`, color: meta.color }}
        >
          <Icon size={16} weight="bold" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-white truncate group-hover:text-[#7DD3FC] transition-colors">
            {marker.label || meta.label}
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] tabular-nums text-[#888]">{formatTime(marker.time)}</span>
            {marker.team && marker.team !== 'neutral' && (
              <span className="text-[10px] text-[#666] truncate max-w-[110px]">· {marker.team}</span>
            )}
            {marker.manually_tagged && (
              <CheckCircle
                size={11}
                weight="fill"
                className="text-[#10B981] flex-shrink-0"
                title="Manually tagged by you"
                data-testid={`marker-row-manual-badge-${marker.id}`}
              />
            )}
          </div>
        </div>
      </button>
      {/* iter99 jersey avatar */}
      {marker.player_number && (
        <div
          data-testid={`marker-row-jersey-${marker.id}`}
          title={marker.player_name || `#${marker.player_number}`}
          className="w-7 h-7 flex flex-col items-center justify-center flex-shrink-0 rounded-full border text-[10px] font-bold tabular-nums"
          style={{ borderColor: meta.color, color: meta.color }}
        >
          {marker.player_number}
        </div>
      )}
      {!marker.player_number && marker.player_name && (
        <span className="text-[10px] text-[#A3A3A3] truncate max-w-[80px]">
          {marker.player_name}
        </span>
      )}
      {/* iter102 — manual tag button */}
      <button
        data-testid={`marker-row-edit-${marker.id}`}
        onClick={() => onEdit(marker)}
        className={`w-7 h-7 flex items-center justify-center flex-shrink-0 transition-colors ${
          hasAttribution
            ? 'opacity-0 group-hover:opacity-100 text-[#666] hover:text-white'
            : 'text-[#FBBF24] hover:bg-[#FBBF24]/10'
        }`}
        title={hasAttribution ? 'Re-tag player' : 'Tag the player in this event'}
        aria-label="Tag player"
      >
        <PencilSimple size={13} weight="bold" />
      </button>
    </div>
  );
};

const MarkersPanel = ({ markers, onSeek, matchId, onMarkerUpdated, onMarkerDeleted }) => {
  const [filter, setFilter] = useState(ALL_FILTER);
  const [editingMarker, setEditingMarker] = useState(null);

  // Sort: by time asc; group counts for the filter pills
  const sorted = useMemo(
    () => [...(markers || [])].sort((a, b) => (a.time || 0) - (b.time || 0)),
    [markers],
  );
  const countsByType = useMemo(() => {
    const m = {};
    for (const x of sorted) m[x.type] = (m[x.type] || 0) + 1;
    return m;
  }, [sorted]);

  const visibleTypes = Object.keys(countsByType)
    .sort((a, b) => (TYPE_META[a]?.priority || 99) - (TYPE_META[b]?.priority || 99));

  const filtered = filter === ALL_FILTER
    ? sorted
    : sorted.filter((m) => m.type === filter);

  if (!sorted.length) return null;

  return (
    <div data-testid="markers-panel" className="bg-[#141414] border border-white/10">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <SoccerBall size={16} weight="bold" className="text-[#FBBF24]" />
          <h3 className="text-xs font-bold uppercase tracking-[0.2em] text-[#E5E5E5]">
            AI Events
          </h3>
          <span data-testid="markers-panel-total" className="text-[10px] text-[#666] tabular-nums">
            {sorted.length}
          </span>
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex flex-wrap gap-1.5 px-3 py-2.5 border-b border-white/5">
        <button
          data-testid="filter-pill-all"
          onClick={() => setFilter(ALL_FILTER)}
          className={`text-[10px] uppercase tracking-wider px-2.5 py-1 rounded-full transition-colors ${
            filter === ALL_FILTER
              ? 'bg-white text-black font-bold'
              : 'bg-white/5 text-[#A3A3A3] hover:bg-white/10'
          }`}
        >
          All · {sorted.length}
        </button>
        {visibleTypes.map((t) => {
          const meta = TYPE_META[t] || TYPE_META.tactical;
          const Icon = meta.icon;
          const active = filter === t;
          return (
            <button
              key={t}
              data-testid={`filter-pill-${t}`}
              onClick={() => setFilter(active ? ALL_FILTER : t)}
              className="text-[10px] uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1.5 transition-colors"
              style={{
                backgroundColor: active ? meta.color : `${meta.color}15`,
                color: active ? '#000' : meta.color,
                fontWeight: active ? 700 : 400,
              }}
            >
              <Icon size={11} weight="bold" />
              {meta.label} · {countsByType[t]}
            </button>
          );
        })}
      </div>

      {/* Marker rows */}
      <div className="max-h-[480px] overflow-y-auto divide-y divide-white/5">
        {filtered.map((m) => (
          <MarkerRow key={m.id} marker={m} onSeek={onSeek} onEdit={setEditingMarker} />
        ))}
        {filtered.length === 0 && (
          <p className="text-xs text-[#666] px-4 py-6 text-center">
            No events matching this filter.
          </p>
        )}
      </div>

      {/* iter102 — Tag-player modal */}
      <TagPlayerModal
        marker={editingMarker}
        matchId={matchId}
        isOpen={!!editingMarker}
        onClose={() => setEditingMarker(null)}
        onMarkerUpdated={onMarkerUpdated}
        onMarkerDeleted={onMarkerDeleted}
      />
    </div>
  );
};

export default MarkersPanel;
