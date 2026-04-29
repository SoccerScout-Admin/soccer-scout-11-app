const formatTime = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
};

const TIMELINE_COLORS = {
  goal: '#FFD700',
  shot: '#FF6B35',
  save: '#4ADE80',
  foul: '#EF4444',
  card: '#EF4444',
  substitution: '#A855F7',
  tactical: '#007AFF',
  chance: '#FFB800',
};

const ANALYSIS_LABELS = {
  tactical: 'Tactical Analysis',
  player_performance: 'Player Performance',
  highlights: 'Match Highlights',
};
const OVERVIEW_LABELS = {
  tactical: 'Tactical Analysis',
  player_performance: 'Player Ratings',
  highlights: 'Highlights',
};

const TAB_DEFS = [
  ['overview', 'Overview'],
  ['tactical', 'Tactical'],
  ['player_performance', 'Players'],
  ['highlights', 'Highlights'],
  ['timeline', 'Timeline'],
];

const OverviewIcon = ({ type }) => {
  if (type === 'tactical') return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18M12 3v18"/>
    </svg>
  );
  if (type === 'player_performance') return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/>
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
    </svg>
  );
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
    </svg>
  );
};

const OverviewTab = ({ analyses, isProcessing, isProcessed, processingStatus, onSelectTab, onStart }) => {
  const getAnalysis = (type) => analyses.find((a) => a.analysis_type === type);
  return (
    <div data-testid="overview-content">
      <h3 className="text-base font-semibold mb-4" style={{ fontFamily: 'Space Grotesk' }}>Analysis Summary</h3>
      {isProcessing ? (
        <div className="text-center py-8">
          <div className="w-10 h-10 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-sm text-[#888]">Your video is being processed by AI...</p>
          <p className="text-xs text-[#555] mt-1">Tactical analysis, player ratings, and highlights will appear here once ready.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {['tactical', 'player_performance', 'highlights'].map((type) => {
            const analysis = getAnalysis(type);
            return (
              <div key={type} data-testid={`overview-${type}`}
                className={`rounded-lg border p-4 cursor-pointer transition-colors ${
                  analysis && analysis.status === 'completed'
                    ? 'border-[#4ADE80]/20 bg-[#0A1A0A] hover:bg-[#0A200A]'
                    : analysis && analysis.status === 'failed'
                    ? 'border-[#EF4444]/20 bg-[#1A0A0A]'
                    : 'border-white/5 bg-white/[0.02] hover:bg-white/[0.04]'
                }`}
                onClick={() => onSelectTab(type)}>
                <div className="flex items-center gap-3 mb-2">
                  <div className={`${analysis?.status === 'completed' ? 'text-[#4ADE80]' : 'text-[#555]'}`}>
                    <OverviewIcon type={type} />
                  </div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-[#888]">{OVERVIEW_LABELS[type]}</span>
                </div>
                {analysis?.status === 'completed' ? (
                  <p className="text-xs text-[#AAA] line-clamp-3">{analysis.content.substring(0, 150)}...</p>
                ) : analysis?.status === 'failed' ? (
                  <p className="text-xs text-[#EF4444]">Failed — click to retry</p>
                ) : (
                  <p className="text-xs text-[#555]">{isProcessing ? 'Processing...' : 'Not generated yet'}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
      {!isProcessing && !isProcessed && processingStatus?.processing_status !== 'queued' && (
        <div className="mt-6 text-center">
          <button data-testid="start-processing-btn" onClick={onStart}
            className="px-6 py-3 rounded-full bg-[#007AFF] text-white text-sm font-medium hover:bg-[#0066DD] transition-colors">
            Start AI Processing
          </button>
          <p className="text-xs text-[#555] mt-2">Generates tactical analysis, player ratings, and highlights automatically</p>
        </div>
      )}
    </div>
  );
};

const TimelineTab = ({ sortedMarkers, onSeek }) => (
  <div data-testid="timeline-content">
    <h3 className="text-base font-semibold mb-4" style={{ fontFamily: 'Space Grotesk' }}>AI Timeline Markers</h3>
    {sortedMarkers.length === 0 ? (
      <div className="text-center py-12">
        <p className="text-sm text-[#666] mb-2">No timeline markers yet.</p>
        <p className="text-xs text-[#555]">Markers are automatically generated during AI processing.</p>
      </div>
    ) : (
      <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
        {sortedMarkers.map((m) => {
          const color = TIMELINE_COLORS[m.type] || '#888';
          return (
            <div key={m.id} data-testid={`timeline-event-${m.id}`}
              className="flex items-center gap-3 px-3 py-2 bg-white/[0.03] rounded hover:bg-white/[0.06] transition-colors cursor-pointer"
              onClick={() => onSeek(m.time)}>
              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: color }} />
              <span className="text-xs font-mono text-[#007AFF] bg-[#007AFF]/10 px-1.5 py-0.5 rounded min-w-[50px] text-center">
                {formatTime(m.time)}
              </span>
              <span className="text-[10px] text-[#666] uppercase w-16 flex-shrink-0">{m.type}</span>
              <span className="text-xs text-[#CCC] flex-1">{m.label}</span>
              <span className="text-[10px] text-[#555]">{m.team}</span>
              <div className="flex gap-0.5">
                {Array.from({ length: m.importance }, (_, i) => (
                  <span key={i} className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    )}
  </div>
);

const AnalysisDetailTab = ({ activeTab, analyses, analyzing, isProcessing, onGenerate }) => {
  const analysis = analyses.find((a) => a.analysis_type === activeTab);

  if (analysis && analysis.status === 'completed') {
    return (
      <div data-testid={`${activeTab}-content`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold" style={{ fontFamily: 'Space Grotesk' }}>{ANALYSIS_LABELS[activeTab]}</h3>
          <button data-testid="regenerate-analysis-btn" onClick={() => onGenerate(activeTab)} disabled={analyzing}
            className="text-xs text-[#007AFF] hover:text-[#0066DD] font-medium disabled:opacity-50">
            {analyzing ? 'Regenerating...' : 'Regenerate'}
          </button>
        </div>
        <div className="text-sm text-[#CCC] leading-relaxed whitespace-pre-wrap">{analysis.content}</div>
      </div>
    );
  }

  if (isProcessing) {
    return (
      <div data-testid={`${activeTab}-content`} className="text-center py-12">
        <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-[#888]">Generating {ANALYSIS_LABELS[activeTab]}...</p>
      </div>
    );
  }

  return (
    <div data-testid={`${activeTab}-content`} className="text-center py-12">
      <p className="text-sm text-[#666] mb-4">No {ANALYSIS_LABELS[activeTab]?.toLowerCase()} generated yet</p>
      <button data-testid="generate-analysis-btn" onClick={() => onGenerate(activeTab)} disabled={analyzing}
        className="px-5 py-2.5 rounded-full bg-[#007AFF] text-white text-sm font-medium hover:bg-[#0066DD] transition-colors disabled:opacity-50 inline-flex items-center gap-2">
        {analyzing ? (
          <>
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Analyzing...
          </>
        ) : (
          'Generate Analysis'
        )}
      </button>
    </div>
  );
};

/**
 * Analysis tabs panel — Overview / Tactical / Players / Highlights / Timeline.
 * Pure presentational; parent owns all state and callbacks.
 */
const AnalysisTabs = ({
  activeTab, onSelectTab,
  analyses, markers, sortedMarkers,
  isProcessing, isProcessed, processingStatus,
  analyzing, onGenerate, onStart, onSeek,
}) => {
  const getAnalysis = (type) => analyses.find((a) => a.analysis_type === type);

  return (
    <div className="bg-[#111] rounded-lg border border-white/10">
      <div className="flex border-b border-white/5">
        {TAB_DEFS.map(([key, label]) => (
          <button key={key} data-testid={`${key}-tab-btn`} onClick={() => onSelectTab(key)}
            className={`px-5 py-3.5 text-xs font-semibold uppercase tracking-wider transition-colors relative ${
              activeTab === key ? 'text-white' : 'text-[#666] hover:text-[#AAA]'
            }`}>
            {label}
            {activeTab === key && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#007AFF]" />}
            {key !== 'overview' && key !== 'timeline' && getAnalysis(key) && getAnalysis(key).status === 'completed' && (
              <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-[#4ADE80] inline-block" />
            )}
            {key === 'timeline' && markers.length > 0 && (
              <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-[#FFD700] inline-block" />
            )}
          </button>
        ))}
      </div>

      <div className="p-6">
        {activeTab === 'overview' ? (
          <OverviewTab
            analyses={analyses}
            isProcessing={isProcessing}
            isProcessed={isProcessed}
            processingStatus={processingStatus}
            onSelectTab={onSelectTab}
            onStart={onStart}
          />
        ) : activeTab === 'timeline' ? (
          <TimelineTab sortedMarkers={sortedMarkers} onSeek={onSeek} />
        ) : (
          <AnalysisDetailTab
            activeTab={activeTab}
            analyses={analyses}
            analyzing={analyzing}
            isProcessing={isProcessing}
            onGenerate={onGenerate}
          />
        )}
      </div>
    </div>
  );
};

export default AnalysisTabs;
