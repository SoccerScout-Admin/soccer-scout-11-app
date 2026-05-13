/**
 * Sticky header + AI processing progress banner + failed banner.
 * Pure presentational; parent owns all state and callbacks.
 */
const VideoAnalysisHeader = ({
  match,
  videoMetadata,
  isProcessing,
  isProcessed,
  processingFailed,
  isAwaitingRoster,
  rosterCount,
  processingStatus,
  serverRestarted,
  processingLabel,
  onBack,
  onDownloadHighlights,
  onReprocess,
  onAddRoster,
  onRunAnyway,
}) => (
  <>
    <header className="sticky top-0 z-50 bg-[#0A0A0A]/95 backdrop-blur-sm border-b border-white/5 px-6 py-3">
      <div className="max-w-[1400px] mx-auto flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button data-testid="back-btn" onClick={onBack}
            className="p-2 rounded-lg hover:bg-white/5 transition-colors">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          </button>
          <div>
            <h1 className="text-lg font-semibold" style={{ fontFamily: 'Space Grotesk' }}>
              {match ? `${match.team_home} vs ${match.team_away}` : 'Video Analysis'}
            </h1>
            {match?.competition && <p className="text-xs text-[#888]">{match.competition} — {new Date(match.date + 'T00:00:00').toLocaleDateString()}</p>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isProcessed && (
            <button data-testid="download-package-btn" onClick={onDownloadHighlights}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-[#1A3A1A] text-[#4ADE80] text-xs font-medium hover:bg-[#1A4A1A] transition-colors">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
              Download Package
            </button>
          )}
          <span className="text-xs text-[#666] bg-white/5 px-3 py-1.5 rounded-full">
            {(videoMetadata.size / (1024 * 1024 * 1024)).toFixed(2)} GB
          </span>
        </div>
      </div>
    </header>

    {isProcessing && (
      <div data-testid="processing-banner" className="bg-gradient-to-r from-[#0C1A3D] to-[#0A0A0A] border-b border-[#1E3A6E]/30 px-6 py-4">
        <div className="max-w-[1400px] mx-auto">
          <div className="flex items-center gap-4">
            <div className="w-8 h-8 rounded-full bg-[#007AFF]/20 flex items-center justify-center flex-shrink-0">
              <div className="w-4 h-4 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-white">
                {serverRestarted ? 'Server restarted — processing resumed automatically' : 'Processing your match video...'}
              </p>
              <p className="text-xs text-[#7AA2D4] mt-0.5">
                {processingStatus.processing_current
                  ? `Running: ${processingLabel[processingStatus.processing_current] || processingStatus.processing_current}`
                  : 'Preparing video for AI analysis'}
                {processingStatus.completed_types && processingStatus.completed_types.length > 0 && (
                  <span className="text-[#4ADE80] ml-2">
                    — {processingStatus.completed_types.length}/4 done
                  </span>
                )}
              </p>
            </div>
            <div className="text-right">
              <p className="text-lg font-bold text-[#007AFF]">{processingStatus.processing_progress || 0}%</p>
            </div>
          </div>
          <div className="mt-3 h-1.5 bg-[#1A1A2E] rounded-full overflow-hidden">
            <div className="h-full bg-[#007AFF] rounded-full transition-all duration-500"
              style={{ width: `${processingStatus.processing_progress || 0}%` }} />
          </div>
          <div className="flex items-center gap-4 mt-3">
            {['tactical', 'player_performance', 'highlights', 'timeline_markers'].map((type) => {
              const isDone = processingStatus.completed_types?.includes(type);
              const isCurrent = processingStatus.processing_current === type;
              const isFailed = processingStatus.failed_types?.includes(type);
              return (
                <div key={type} className="flex items-center gap-1.5 text-[10px]">
                  {isDone ? (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                  ) : isCurrent ? (
                    <div className="w-3 h-3 border border-[#007AFF] border-t-transparent rounded-full animate-spin" />
                  ) : isFailed ? (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
                  ) : (
                    <div className="w-3 h-3 rounded-full border border-[#333]" />
                  )}
                  <span className={isDone ? 'text-[#4ADE80]' : isCurrent ? 'text-[#007AFF]' : isFailed ? 'text-[#EF4444]' : 'text-[#555]'}>
                    {processingLabel[type]}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    )}

    {processingFailed && (
      <div data-testid="processing-failed-banner" className="bg-[#1A0C0C] border-b border-[#6E1E1E]/30 px-6 py-4">
        <div className="max-w-[1400px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
            <div>
              <p className="text-sm text-[#EF4444]">Processing encountered an issue</p>
              <p className="text-xs text-[#888] mt-0.5">
                {processingStatus.processing_error && (processingStatus.processing_error.toLowerCase().includes('budget') || processingStatus.processing_error.toLowerCase().includes('quota') || processingStatus.processing_error.toLowerCase().includes('balance'))
                  ? 'AI budget limit reached. Add balance in Profile > Universal Key to continue.'
                  : processingStatus.completed_types?.length > 0
                  ? `${processingStatus.completed_types.length}/4 analyses completed. ${processingStatus.failed_types?.length || 0} failed.`
                  : processingStatus.processing_error || 'Some analyses may not have completed'}
              </p>
            </div>
          </div>
          <button data-testid="retry-processing-btn" onClick={onReprocess}
            className="px-4 py-2 rounded-full bg-[#EF4444]/10 text-[#EF4444] text-xs font-medium hover:bg-[#EF4444]/20 transition-colors">
            {processingStatus.completed_types?.length > 0 ? 'Resume Failed' : 'Retry Processing'}
          </button>
        </div>
      </div>
    )}

    {isAwaitingRoster && (
      <div data-testid="awaiting-roster-banner" className="bg-gradient-to-r from-[#2A1A05] to-[#0A0A0A] border-b border-[#FBBF24]/30 px-6 py-4">
        <div className="max-w-[1400px] mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-[#FBBF24]/15 border border-[#FBBF24]/40 flex items-center justify-center flex-shrink-0">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FBBF24" strokeWidth="2.5">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-white">
                Video uploaded — waiting on roster before AI analysis runs
              </p>
              <p className="text-xs text-[#A3A3A3] mt-0.5">
                {rosterCount === 0
                  ? 'Add players first for accurate tactical attribution, or run AI without roster context.'
                  : `${rosterCount} player${rosterCount === 1 ? '' : 's'} added — ready when you are.`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              data-testid="awaiting-roster-add-btn"
              onClick={onAddRoster}
              className="px-4 py-2 bg-[#FBBF24] hover:bg-[#e5a91e] text-black text-xs font-bold tracking-wider uppercase transition-colors">
              {rosterCount === 0 ? 'Add Roster' : 'Edit Roster'}
            </button>
            <button
              data-testid="awaiting-roster-run-anyway-btn"
              onClick={onRunAnyway}
              className="px-4 py-2 border border-white/15 text-white hover:bg-white/5 text-xs font-bold tracking-wider uppercase transition-colors">
              {rosterCount > 0 ? 'Start Analysis' : 'Run Anyway'}
            </button>
          </div>
        </div>
      </div>
    )}
  </>
);

export default VideoAnalysisHeader;
