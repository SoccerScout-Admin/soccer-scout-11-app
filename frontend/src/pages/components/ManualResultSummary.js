/**
 * ManualResultSummary
 * -------------------
 * Read-only summary card for a match's saved manual result. Renders the score
 * + outcome chip, list of key events, coach notes, and AI recap (when present).
 *
 * Extracted from ManualResultForm.js during the iter53 refactor — the parent
 * was 491 lines and toggled between summary and editor views. Splitting them
 * lets each focus on its own concerns. Parent owns all state + handlers and
 * passes them in.
 */
import { Trophy, Trash, Check, PencilSimple, ShareNetwork } from '@phosphor-icons/react';
import ShareRecapModal from './ShareRecapModal';

const EVENT_TYPES = [
  { key: 'goal', label: 'Goal', color: '#10B981' },
  { key: 'shot', label: 'Shot', color: '#60A5FA' },
  { key: 'save', label: 'Save', color: '#A855F7' },
  { key: 'foul', label: 'Foul', color: '#FBBF24' },
  { key: 'card', label: 'Card', color: '#EF4444' },
  { key: 'sub', label: 'Sub', color: '#A3A3A3' },
  { key: 'note', label: 'Note', color: '#CCCCCC' },
];

const ManualResultSummary = ({
  match, existing, players,
  aiSummary, finishing, error,
  recapShareToken, shareRecapOpen,
  onEdit, onFinish, onUnlock, onDelete,
  onOpenShareRecap, onCloseShareRecap, onRecapTokenChange,
}) => {
  const outcome = existing.outcome;
  const outcomeColor = outcome === 'W' ? '#10B981' : outcome === 'L' ? '#EF4444' : '#FBBF24';
  const isLocked = !!existing.is_final;

  return (
    <div data-testid="manual-result-summary" className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-[#60A5FA]/30 p-4 sm:p-6 mb-6">
      {/* Header — title chip + action buttons */}
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
            <button data-testid="edit-manual-result-btn" onClick={onEdit}
              className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors">
              <PencilSimple size={14} weight="bold" /> Edit
            </button>
          )}
          {!isLocked && (
            <button data-testid="finish-match-btn" onClick={onFinish} disabled={finishing}
              className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 bg-gradient-to-r from-[#10B981] to-[#059669] text-white hover:opacity-90 transition-opacity disabled:opacity-50">
              {finishing ? (
                <><div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" /> Generating recap…</>
              ) : (
                <><Check size={14} weight="bold" /> Finish Match</>
              )}
            </button>
          )}
          {isLocked && (
            <button data-testid="unlock-match-btn" onClick={onUnlock}
              className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 border border-[#FBBF24]/30 text-[#FBBF24] hover:bg-[#FBBF24]/10 transition-colors">
              <PencilSimple size={14} weight="bold" /> Unlock
            </button>
          )}
          <button data-testid="delete-manual-result-btn" onClick={onDelete}
            disabled={isLocked}
            className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-2 border border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/15 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
            <Trash size={14} weight="bold" /> Remove
          </button>
        </div>
      </div>

      {/* Scoreline — home + outcome chip + away */}
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

      {/* Key events */}
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
                {player && <span className="text-xs text-[#FBBF24]">#{player.number ?? '?'} {player.name}</span>}
                {ev.description && <span className="text-xs text-[#CCCCCC] truncate">{ev.description}</span>}
              </div>
            );
          })}
        </div>
      )}

      {/* Coach notes */}
      {existing.notes && (
        <div className="mt-4 bg-[#0A0A0A] border border-white/5 p-3">
          <div className="text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-1">Coach's Notes</div>
          <p className="text-sm text-[#E5E5E5] whitespace-pre-wrap leading-relaxed">{existing.notes}</p>
        </div>
      )}

      {/* AI recap card */}
      {aiSummary && (
        <div data-testid="ai-recap" className="mt-4 bg-gradient-to-br from-[#1B0F2E] to-[#0A0A0A] border border-[#A855F7]/30 p-4">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 bg-[#A855F7]/15 border border-[#A855F7]/30 flex items-center justify-center flex-shrink-0">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#A855F7">
                  <path d="M12 2L9.91 8.26L2 9.27L7.91 14.14L6.18 22L12 18.27L17.82 22L16.09 14.14L22 9.27L14.09 8.26L12 2Z"/>
                </svg>
              </div>
              <div className="text-[10px] tracking-[0.2em] uppercase text-[#A855F7] font-bold">AI Match Recap</div>
            </div>
            <button data-testid="share-recap-btn" onClick={onOpenShareRecap}
              className={`flex items-center gap-1.5 text-[10px] font-bold tracking-wider uppercase px-2.5 py-1.5 border transition-colors ${
                recapShareToken
                  ? 'bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30 hover:bg-[#10B981]/25'
                  : 'bg-[#A855F7]/15 text-[#A855F7] border-[#A855F7]/30 hover:bg-[#A855F7]/25'
              }`}>
              <ShareNetwork size={12} weight="bold" />
              {recapShareToken ? 'Sharing On' : 'Share'}
            </button>
          </div>
          <p className="text-sm text-[#E5E5E5] leading-relaxed whitespace-pre-wrap">{aiSummary}</p>
        </div>
      )}

      {error && (
        <div data-testid="finish-error" className="mt-3 text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 px-3 py-2">
          {error}
        </div>
      )}

      <ShareRecapModal open={shareRecapOpen} matchId={match.id} initialToken={recapShareToken}
        onClose={onCloseShareRecap}
        onTokenChange={onRecapTokenChange} />
    </div>
  );
};

export default ManualResultSummary;
