const formatTime = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
};

/**
 * Trim Panel — lets coaches select a time range to focus AI analysis on a specific section.
 */
const TrimPanel = ({
  trimStart, setTrimStart,
  trimEnd, setTrimEnd,
  videoDuration, currentTimestamp,
  analyzing, processingLabel,
  onClose, onAnalyze,
}) => (
  <div data-testid="trim-panel" className="bg-[#111] rounded-lg border border-[#A855F7]/30 p-5">
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-sm font-semibold" style={{ fontFamily: 'Space Grotesk' }}>Analyze Video Section</h3>
      <button data-testid="close-trim-panel" onClick={onClose} className="text-[#666] hover:text-white">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>
    <p className="text-xs text-[#888] mb-3">Select a time range to focus AI analysis on a specific section (e.g., first half, second half, a specific play).</p>
    <div className="grid grid-cols-2 gap-3 mb-3">
      <div>
        <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Start Time</label>
        <div className="flex gap-2">
          <input data-testid="trim-start-input" type="number" step="1" min="0" max={videoDuration}
            value={trimStart} onChange={(e) => setTrimStart(Math.max(0, parseFloat(e.target.value) || 0))}
            className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#A855F7] focus:outline-none" />
          <button data-testid="trim-start-now-btn" onClick={() => setTrimStart(Math.floor(currentTimestamp))}
            className="px-3 py-2 rounded-lg bg-white/10 text-[#A855F7] text-xs font-medium">Now</button>
        </div>
        <span className="text-[10px] text-[#555]">{formatTime(trimStart)}</span>
      </div>
      <div>
        <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">End Time</label>
        <div className="flex gap-2">
          <input data-testid="trim-end-input" type="number" step="1" min="0" max={videoDuration}
            value={trimEnd} onChange={(e) => setTrimEnd(Math.min(videoDuration, parseFloat(e.target.value) || 0))}
            className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#A855F7] focus:outline-none" />
          <button data-testid="trim-end-now-btn" onClick={() => setTrimEnd(Math.floor(currentTimestamp))}
            className="px-3 py-2 rounded-lg bg-white/10 text-[#A855F7] text-xs font-medium">Now</button>
        </div>
        <span className="text-[10px] text-[#555]">{formatTime(trimEnd)}</span>
      </div>
    </div>
    <p className="text-xs text-[#A855F7] mb-3">Duration: {formatTime(Math.max(0, trimEnd - trimStart))}</p>
    <div className="flex gap-2">
      {['tactical', 'player_performance', 'highlights'].map((type) => (
        <button key={type} data-testid={`trim-analyze-${type}-btn`}
          onClick={() => onAnalyze(type)} disabled={analyzing || trimStart >= trimEnd}
          className="flex-1 px-3 py-2.5 rounded-lg bg-[#A855F7] hover:bg-[#9333EA] text-white text-xs font-medium transition-colors disabled:opacity-40">
          {analyzing ? 'Analyzing...' : processingLabel[type] || type}
        </button>
      ))}
    </div>
  </div>
);

export default TrimPanel;
