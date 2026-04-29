import { Sparkle, X, Check } from '@phosphor-icons/react';

const TagPlayersModal = ({
  taggingClip,
  setTaggingClip,
  tagSearch,
  setTagSearch,
  tagSelection,
  toggleTag,
  savingTags,
  saveClipTags,
  aiSuggesting,
  aiSuggestions,
  handleAiSuggest,
  players,
}) => {
  if (!taggingClip) return null;
  return (
    <div data-testid="tag-modal-overlay" onClick={() => !savingTags && setTaggingClip(null)}
      className="fixed inset-0 bg-black/70 z-[200] flex items-center justify-center px-4">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-white/10 max-w-lg w-full max-h-[80vh] flex flex-col rounded-lg">
        <div className="p-5 border-b border-white/10">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h3 className="text-xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>Tag Players</h3>
              <p className="text-xs text-[#A3A3A3] mt-0.5 truncate">{taggingClip.title}</p>
            </div>
            <button data-testid="close-tag-modal" onClick={() => setTaggingClip(null)}
              className="p-1 text-[#666] hover:text-white">
              <X size={20} />
            </button>
          </div>
          <input data-testid="tag-search-input" type="text"
            value={tagSearch}
            onChange={(e) => setTagSearch(e.target.value)}
            placeholder="Search by name or jersey number..."
            className="w-full mt-3 bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 text-sm focus:outline-none focus:border-[#FBBF24] rounded" />
          <button data-testid="ai-suggest-btn" onClick={handleAiSuggest} disabled={aiSuggesting}
            className="mt-3 w-full text-xs py-2.5 bg-gradient-to-r from-[#A855F7] to-[#FBBF24] hover:opacity-90 disabled:opacity-50 text-black font-bold tracking-wider uppercase rounded flex items-center justify-center gap-2 transition-opacity">
            {aiSuggesting ? (
              <>
                <div className="w-3 h-3 border-2 border-black border-t-transparent rounded-full animate-spin" />
                Analyzing frame…
              </>
            ) : (
              <>
                <Sparkle size={14} weight="fill" />
                AI Suggest Players
              </>
            )}
          </button>
          {aiSuggestions && (
            <div data-testid="ai-suggestions-result"
              className="mt-2 text-[10px] tracking-wider text-[#FBBF24] bg-[#FBBF24]/10 px-2 py-1.5 border border-[#FBBF24]/20">
              {aiSuggestions.suggestions.length > 0
                ? <>AI detected jersey #{aiSuggestions.raw_numbers.join(', #')} — {aiSuggestions.suggestions.length} matched to roster (pre-selected below).</>
                : aiSuggestions.raw_numbers.length > 0
                  ? <>AI saw jersey #{aiSuggestions.raw_numbers.join(', #')} but no roster match.</>
                  : <>AI couldn't read any jersey numbers from this clip's frame.</>
              }
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {players.length === 0 ? (
            <p className="text-center text-sm text-[#666] py-8">No players in roster yet. Add players from the match detail page.</p>
          ) : (
            players
              .filter(p => {
                const q = tagSearch.toLowerCase();
                if (!q) return true;
                return (p.name || '').toLowerCase().includes(q) || String(p.number ?? '').includes(q);
              })
              .map(p => {
                const selected = tagSelection.includes(p.id);
                return (
                  <button key={p.id} data-testid={`tag-player-${p.id}`}
                    onClick={() => toggleTag(p.id)}
                    className={`w-full flex items-center gap-3 p-3 transition-colors text-left rounded ${
                      selected ? 'bg-[#FBBF24]/10 border border-[#FBBF24]/40' : 'bg-[#0A0A0A] border border-white/10 hover:bg-[#1A1A1A]'
                    }`}>
                    <div className={`w-5 h-5 flex-shrink-0 rounded border flex items-center justify-center ${
                      selected ? 'bg-[#FBBF24] border-[#FBBF24]' : 'border-white/30'
                    }`}>
                      {selected && <Check size={12} weight="bold" color="black" />}
                    </div>
                    <span className="text-xl font-bold text-[#007AFF] flex-shrink-0 min-w-[28px] text-center" style={{ fontFamily: 'Bebas Neue' }}>
                      {p.number ?? '—'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-white truncate">{p.name}</div>
                      <div className="text-[10px] text-[#666] tracking-wider">{p.position || 'No position'}</div>
                    </div>
                  </button>
                );
              })
          )}
        </div>

        <div className="p-4 border-t border-white/10 flex items-center justify-between gap-3">
          <span className="text-xs text-[#A3A3A3]">
            {tagSelection.length} player{tagSelection.length === 1 ? '' : 's'} selected
          </span>
          <div className="flex gap-2">
            <button onClick={() => setTaggingClip(null)} disabled={savingTags}
              className="px-4 py-2 border border-white/10 text-[#A3A3A3] hover:text-white text-xs font-bold uppercase rounded">
              Cancel
            </button>
            <button data-testid="save-tags-btn" onClick={saveClipTags} disabled={savingTags}
              className="px-5 py-2 bg-[#FBBF24] hover:bg-[#FCD34D] disabled:opacity-50 text-black text-xs font-bold tracking-wider uppercase rounded">
              {savingTags ? 'Saving…' : 'Save Tags'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TagPlayersModal;
