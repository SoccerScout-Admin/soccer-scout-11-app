import { formatTime } from './utils/time';

const ClipCard = ({
  clip, players, isSelected,
  downloadingClip,
  onToggleSelect, onPlay, onDownload, onTag, onShare, onDelete, onGenerateCloseUp,
}) => {
  const closeUpStatus = clip.close_up_status; // pending | processing | ready | failed
  const isGoal = (clip.clip_type || '').toLowerCase() === 'goal';
  const showGenerateBtn = !closeUpStatus || closeUpStatus === 'failed';

  return (
  <div data-testid={`clip-${clip.id}`}
    className={`rounded-lg p-3 hover:bg-white/[0.06] transition-colors group ${
      isSelected ? 'bg-[#A855F7]/10 border border-[#A855F7]/30' : 'bg-white/[0.03]'
    }`}>
    <div className="flex items-start gap-2">
      <input type="checkbox" data-testid={`select-clip-${clip.id}`}
        checked={isSelected}
        onChange={() => onToggleSelect(clip.id)}
        className="mt-1 accent-[#A855F7] w-3.5 h-3.5 flex-shrink-0 cursor-pointer" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white truncate">{clip.title}</p>
        <p className="text-[10px] text-[#666] mt-0.5">
          {formatTime(clip.start_time)} — {formatTime(clip.end_time)} · <span className="uppercase">{clip.clip_type}</span>
        </p>
        {closeUpStatus === 'ready' && (
          <span data-testid={`closeup-ready-${clip.id}`}
            className="inline-block mt-1 text-[9px] font-bold uppercase tracking-wider text-[#10B981] bg-[#10B981]/10 border border-[#10B981]/30 px-1.5 py-0.5 rounded">
            🎬 Wide + Close-up
          </span>
        )}
        {(closeUpStatus === 'pending' || closeUpStatus === 'processing') && (
          <span data-testid={`closeup-processing-${clip.id}`}
            className="inline-flex items-center gap-1 mt-1 text-[9px] font-bold uppercase tracking-wider text-[#FBBF24] bg-[#FBBF24]/10 border border-[#FBBF24]/30 px-1.5 py-0.5 rounded">
            <span className="w-1.5 h-1.5 bg-[#FBBF24] rounded-full animate-pulse" />
            Generating close-up
          </span>
        )}
        {closeUpStatus === 'failed' && (
          <span data-testid={`closeup-failed-${clip.id}`}
            className="inline-block mt-1 text-[9px] font-bold uppercase tracking-wider text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 px-1.5 py-0.5 rounded">
            Close-up failed
          </span>
        )}
      </div>
      <button data-testid={`delete-clip-${clip.id}-btn`} onClick={() => onDelete(clip.id)}
        className="text-[#444] hover:text-[#EF4444] opacity-0 group-hover:opacity-100 transition-opacity ml-2">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>
    {clip.description && <p className="text-[10px] text-[#555] mt-1 line-clamp-2">{clip.description}</p>}
    {clip.player_ids && clip.player_ids.length > 0 && (
      <div className="flex flex-wrap gap-1 mt-1">
        {clip.player_ids.map((pid) => {
          const player = players.find((p) => p.id === pid);
          return player ? (
            <span key={pid} className="text-[9px] text-[#007AFF] bg-[#007AFF]/10 px-1 py-0.5 rounded">
              #{player.number ?? '?'} {player.name}
            </span>
          ) : null;
        })}
      </div>
    )}
    <div className="flex items-center gap-3 mt-2 flex-wrap">
      <button data-testid={`play-clip-${clip.id}-btn`} onClick={() => onPlay(clip)}
        className="flex items-center gap-1 text-[10px] text-[#007AFF] font-medium hover:text-[#0066DD]">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Play
      </button>
      <button data-testid={`download-clip-${clip.id}-btn`}
        onClick={() => onDownload(clip.id, clip.title)}
        disabled={downloadingClip === clip.id}
        className="flex items-center gap-1 text-[10px] text-[#4ADE80] font-medium hover:text-[#6AEE9A] disabled:opacity-50">
        {downloadingClip === clip.id ? (
          <><div className="w-2.5 h-2.5 border border-[#4ADE80] border-t-transparent rounded-full animate-spin" /> Extracting...</>
        ) : (
          <><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg> Download MP4</>
        )}
      </button>
      <button data-testid={`tag-clip-${clip.id}-btn`}
        onClick={() => onTag(clip)}
        className="flex items-center gap-1 text-[10px] text-[#FBBF24] font-medium hover:text-[#FCD34D]">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
        {clip.player_ids?.length > 0 ? `Tags (${clip.player_ids.length})` : 'Tag'}
      </button>
      <button data-testid={`share-clip-${clip.id}-btn`}
        onClick={() => onShare(clip)}
        className="flex items-center gap-1 text-[10px] text-[#A855F7] font-medium hover:text-[#C084FC]">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
        {clip.share_token ? 'Shared' : 'Share'}
      </button>
      {showGenerateBtn && !isGoal && (
        <button data-testid={`closeup-${clip.id}-btn`}
          onClick={() => onGenerateCloseUp(clip)}
          className="flex items-center gap-1 text-[10px] text-[#10B981] font-medium hover:text-[#34D399]">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
          {closeUpStatus === 'failed' ? 'Retry close-up' : 'Add close-up'}
        </button>
      )}
    </div>
  </div>
  );
};

/**
 * Right-sidebar Clips panel — list, batch select, share-as-reel, download-zip, individual clip actions.
 */
const ClipsSidebar = ({
  clips, players, selectedClips,
  downloadingClip, downloadingZip,
  onToggleSelect, onShareReel, onDownloadZipSelected, onDownloadAllZip,
  onDeleteClip, onPlayClip, onDownloadClip, onTagClip, onShareClip, onGenerateCloseUp,
}) => (
  <div className="bg-[#111] rounded-lg border border-white/10 p-5">
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-[#888]">
        Clips ({clips.length})
      </h3>
      {clips.length > 0 && (
        <div className="flex items-center gap-2">
          {selectedClips.length > 0 && (
            <>
              <button data-testid="share-selected-reel-btn" onClick={onShareReel}
                className="text-[10px] text-[#A855F7] font-medium hover:text-[#C084FC]">
                Share {selectedClips.length} as Reel
              </button>
              <button data-testid="download-selected-zip-btn"
                onClick={onDownloadZipSelected} disabled={downloadingZip}
                className="text-[10px] text-[#A855F7] font-medium hover:text-[#C084FC] disabled:opacity-50">
                {downloadingZip ? 'Zipping...' : `Download ${selectedClips.length} as ZIP`}
              </button>
            </>
          )}
          <button data-testid="download-all-zip-btn"
            onClick={onDownloadAllZip} disabled={downloadingZip}
            className="text-[10px] text-[#4ADE80] font-medium hover:text-[#6AEE9A] disabled:opacity-50">
            {downloadingZip ? 'Zipping...' : 'Download All ZIP'}
          </button>
        </div>
      )}
    </div>
    {clips.length === 0 ? (
      <div className="text-center py-6">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#333" strokeWidth="1.5" className="mx-auto mb-2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12"/></svg>
        <p className="text-xs text-[#555]">No clips yet. Use the clip tool while watching.</p>
      </div>
    ) : (
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {clips.map((clip) => (
          <ClipCard key={clip.id}
            clip={clip}
            players={players}
            isSelected={selectedClips.includes(clip.id)}
            downloadingClip={downloadingClip}
            onToggleSelect={onToggleSelect}
            onPlay={onPlayClip}
            onDownload={onDownloadClip}
            onTag={onTagClip}
            onShare={onShareClip}
            onDelete={onDeleteClip}
            onGenerateCloseUp={onGenerateCloseUp}
          />
        ))}
      </div>
    )}
  </div>
);

export default ClipsSidebar;
