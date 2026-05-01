import { CalendarBlank, Trophy, VideoCamera, UploadSimple, Trash } from '@phosphor-icons/react';

const VideoStatus = ({ match }) => {
  const status = match.processing_status;
  if (status === 'completed') {
    return (
      <div className="flex items-center gap-2 text-[#4ADE80] text-sm">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
        <span>Analysis Ready</span>
      </div>
    );
  }
  if (status === 'processing' || status === 'queued') {
    const pct = Math.max(0, Math.min(100, match.processing_progress || 0));
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-[#007AFF] text-sm">
          <div className="w-3 h-3 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
          <span>Processing · {pct}%</span>
        </div>
        <div className="h-1 bg-[#0A0A0A] rounded-full overflow-hidden" data-testid="match-card-progress-bar">
          <div className="h-full bg-[#007AFF] transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }
  if (status === 'failed') {
    return (
      <div className="flex items-center gap-2 text-[#EF4444] text-sm">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>
        </svg>
        <span>Processing Failed</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-[#39FF14] text-sm">
      <VideoCamera size={16} />
      <span>Video uploaded</span>
    </div>
  );
};

const ManualResultBadge = ({ match }) => {
  const { home_score, away_score, outcome } = match.manual_result;
  const color = outcome === 'W' ? '#10B981' : outcome === 'L' ? '#EF4444' : '#FBBF24';
  return (
    <div className="mt-4 flex items-center gap-2 flex-wrap" data-testid={`manual-badge-${match.id}`}>
      <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#60A5FA] bg-[#60A5FA]/15 border border-[#60A5FA]/30 px-2 py-1">
        No Video — Manual Result
      </span>
      <span className="text-sm font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>
        {home_score} – {away_score}
      </span>
      {outcome && (
        <span className="text-[10px] tracking-wider uppercase font-bold px-1.5 py-0.5"
          style={{ color, backgroundColor: color + '20' }}>
          {outcome}
        </span>
      )}
    </div>
  );
};

const MatchCard = ({ match, folders, selectionMode, isSelected, onNavigate, onToggleSelect, onMoveMatch, onDeleteMatch }) => (
  <div data-testid={`match-card-${match.id}`}
    className={`bg-[#141414] border p-6 hover:bg-[#1F1F1F] transition-colors cursor-pointer group relative ${
      selectionMode && isSelected ? 'border-[#FBBF24]' : 'border-white/10'
    }`}
    onClick={() => selectionMode ? onToggleSelect(match.id) : onNavigate(`/match/${match.id}`)}>
    {selectionMode && (
      <div data-testid={`select-${match.id}`}
        className={`absolute top-3 left-3 w-6 h-6 rounded border-2 flex items-center justify-center ${
          isSelected ? 'bg-[#FBBF24] border-[#FBBF24]' : 'bg-transparent border-white/30'
        }`}>
        {isSelected && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="3">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        )}
      </div>
    )}
    {!selectionMode && (
      <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-2"
        onClick={(e) => e.stopPropagation()}>
        {folders.length > 0 && (
          <select data-testid={`move-match-${match.id}-select`}
            value={match.folder_id || ''}
            onChange={(e) => onMoveMatch(match.id, e.target.value || null)}
            className="bg-[#0A0A0A] border border-white/10 text-[10px] text-[#A3A3A3] px-2 py-1 focus:outline-none focus:border-[#007AFF]">
            <option value="">No folder</option>
            {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        )}
        <button data-testid={`delete-match-${match.id}-btn`}
          onClick={(e) => { e.stopPropagation(); onDeleteMatch(match); }}
          aria-label={`Delete ${match.team_home} vs ${match.team_away}`}
          className="w-7 h-7 flex items-center justify-center border border-white/10 bg-[#0A0A0A] text-[#A3A3A3] hover:text-[#EF4444] hover:border-[#EF4444]/40 transition-colors">
          <Trash size={14} weight="bold" />
        </button>
      </div>
    )}
    <div className="flex items-center gap-2 mb-4">
      <Trophy size={20} className="text-[#007AFF]" />
      <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{match.competition || 'Friendly'}</p>
    </div>
    <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
      {match.team_home} vs {match.team_away}
    </h3>
    <div className="flex items-center gap-2 text-sm text-[#A3A3A3]">
      <CalendarBlank size={16} />
      <span>{new Date(match.date + 'T00:00:00').toLocaleDateString()}</span>
    </div>
    {match.video_id && <div className="mt-4"><VideoStatus match={match} /></div>}
    {!match.video_id && match.has_manual_result && match.manual_result && (
      <ManualResultBadge match={match} />
    )}
    {!match.video_id && !match.has_manual_result && (
      <div className="mt-4 flex items-center gap-2 text-[#A3A3A3] text-xs" data-testid={`pending-badge-${match.id}`}>
        <UploadSimple size={14} />
        <span>No video or result yet</span>
      </div>
    )}
  </div>
);

export default MatchCard;
