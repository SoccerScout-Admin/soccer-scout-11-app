const formatTime = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
};

/**
 * Right-sidebar Annotations panel — coach notes/tactical/key-moments tied to a timestamp.
 */
const AnnotationsSidebar = ({ annotations, players, onDelete, onSeek }) => (
  <div className="bg-[#111] rounded-lg border border-white/10 p-5">
    <h3 className="text-xs font-semibold uppercase tracking-wider text-[#888] mb-4">
      Annotations ({annotations.length})
    </h3>
    {annotations.length === 0 ? (
      <div className="text-center py-6">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#333" strokeWidth="1.5" className="mx-auto mb-2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
        <p className="text-xs text-[#555]">No annotations yet. Add notes while watching.</p>
      </div>
    ) : (
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {annotations.map((ann) => {
          const player = ann.player_id ? players.find((p) => p.id === ann.player_id) : null;
          return (
            <div key={ann.id} data-testid={`annotation-${ann.id}`}
              className="bg-white/[0.03] rounded-lg p-3 hover:bg-white/[0.06] transition-colors group">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded">
                    {formatTime(ann.timestamp)}
                  </span>
                  <span className="text-[10px] text-[#555] uppercase">{ann.annotation_type.replace('_', ' ')}</span>
                </div>
                <button data-testid={`delete-annotation-${ann.id}-btn`} onClick={() => onDelete(ann.id)}
                  className="text-[#444] hover:text-[#EF4444] opacity-0 group-hover:opacity-100 transition-opacity">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
                </button>
              </div>
              <p className="text-xs text-[#CCC] mt-1.5">{ann.content}</p>
              {player && (
                <span className="inline-flex items-center gap-1 mt-1 text-[10px] text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded">
                  #{player.number || '?'} {player.name}
                </span>
              )}
              <button data-testid={`seek-annotation-${ann.id}-btn`} onClick={() => onSeek(ann.timestamp)}
                className="text-[10px] text-[#007AFF] font-medium mt-1.5 hover:text-[#0066DD] block">
                Jump to moment
              </button>
            </div>
          );
        })}
      </div>
    )}
  </div>
);

export default AnnotationsSidebar;
