/**
 * Reusable AI-processing progress banner shown on MatchDetail while any
 * analysis step is running. Pure presentational — parent passes the same
 * `videoMeta` / `processing_status` shape that `/api/videos/{id}/processing-status`
 * returns.
 */
import { useEffect, useRef, useState } from 'react';
import { useProcessingEta } from './hooks/useProcessingEta';

const STEPS = [
  { key: 'tactical', label: 'Tactical Analysis' },
  { key: 'player_performance', label: 'Player Ratings' },
  { key: 'highlights', label: 'Highlights' },
  { key: 'timeline_markers', label: 'Timeline Markers' },
];

// Rotating flavor messages keyed to the active analysis. Pure presentation —
// makes the wait feel less static. Mirrors the wireframe's "real-time status
// updates" feed without needing a backend log table.
const STATUS_FLAVOR = {
  tactical: [
    'Tracking ball trajectory…',
    'Identifying formations…',
    'Detecting pressing triggers…',
    'Mapping defensive line…',
    'Analyzing transition moments…',
  ],
  player_performance: [
    'Detecting player movements…',
    'Calculating heat maps…',
    'Tracking individual touches…',
    'Scoring decision-making…',
    'Rating off-ball runs…',
  ],
  highlights: [
    'Scanning for goal attempts…',
    'Detecting key passes…',
    'Picking standout moments…',
    'Clipping highlight sequences…',
  ],
  timeline_markers: [
    'Placing event markers…',
    'Auto-tagging goals & saves…',
    'Indexing timeline by player…',
    'Finalising markers…',
  ],
  queued: [
    'Queued — waiting for an AI slot…',
    'Preparing video chunks…',
  ],
};

const StepIcon = ({ done, current, failed }) => {
  if (done) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="2">
        <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
        <polyline points="22 4 12 14.01 9 11.01"/>
      </svg>
    );
  }
  if (current) {
    return <div className="w-3.5 h-3.5 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />;
  }
  if (failed) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2">
        <circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>
      </svg>
    );
  }
  return <div className="w-3.5 h-3.5 rounded-full border border-[#2A2A2A]" />;
};

const ProcessingProgressBar = ({ videoMeta, onRetry }) => {
  const eta = useProcessingEta(videoMeta);
  const [statusFeed, setStatusFeed] = useState([]);
  const feedRef = useRef(null);

  const status = videoMeta?.processing_status;
  const current = videoMeta?.processing_current;
  const isActive = status === 'processing' || status === 'queued';

  // Rotate flavor messages while processing — pushes a new one every 3s.
  useEffect(() => {
    if (!isActive) { setStatusFeed([]); return undefined; }
    const key = current && STATUS_FLAVOR[current] ? current : (status === 'queued' ? 'queued' : 'tactical');
    const pool = STATUS_FLAVOR[key] || STATUS_FLAVOR.tactical;
    let idx = 0;
    const pushOne = () => {
      const msg = pool[idx % pool.length];
      idx += 1;
      setStatusFeed((prev) => {
        const next = [...prev, { id: Date.now() + Math.random(), msg }];
        return next.slice(-8);
      });
    };
    pushOne();
    const id = setInterval(pushOne, 3000);
    return () => clearInterval(id);
  }, [isActive, current, status]);

  // Keep feed scrolled to bottom
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [statusFeed]);

  if (!videoMeta || !videoMeta.processing_status) return null;

  const pct = Math.max(0, Math.min(100, videoMeta.processing_progress || 0));
  const completed = videoMeta.completed_types || [];
  const failed = videoMeta.failed_types || [];
  const isFailed = status === 'failed';

  if (!isActive && !isFailed) return null;  // completed → don't render

  const currentLabel = current ? STEPS.find(s => s.key === current)?.label || current : null;

  return (
    <div data-testid="match-processing-progress"
      className={`border p-5 mb-6 ${
        isFailed ? 'bg-gradient-to-r from-[#1A0C0C] to-[#0A0A0A] border-[#6E1E1E]/40'
                 : 'bg-gradient-to-r from-[#0C1A3D] to-[#0A0A0A] border-[#1E3A6E]/40'
      }`}>
      <div className="flex items-center gap-4 mb-4">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 ${
          isFailed ? 'bg-[#EF4444]/15' : 'bg-[#007AFF]/15'
        }`}>
          {isFailed ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>
            </svg>
          ) : (
            <div className="w-5 h-5 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-white tracking-wider uppercase" style={{ fontFamily: 'Space Grotesk' }}>
            {isFailed ? 'Processing Failed' : status === 'queued' ? 'Queued for AI analysis' : 'AI Analysis in Progress'}
          </p>
          <p className="text-xs text-[#7AA2D4] mt-0.5 truncate">
            {isFailed
              ? (videoMeta.processing_error && (videoMeta.processing_error.toLowerCase().includes('budget') || videoMeta.processing_error.toLowerCase().includes('quota'))
                  ? 'AI budget limit reached. Add balance in Profile → Universal Key to continue.'
                  : `${completed.length}/4 analyses completed — ${failed.length} failed`)
              : currentLabel
              ? `Running: ${currentLabel}`
              : 'Preparing video for AI analysis'}
            {!isFailed && completed.length > 0 && (
              <span className="text-[#10B981] ml-2">· {completed.length}/4 done</span>
            )}
          </p>
          {!isFailed && eta && (
            <p data-testid="processing-eta" className="text-[10px] text-[#FBBF24] mt-1 tracking-[0.15em] uppercase font-bold">
              {eta}
            </p>
          )}
        </div>
        <div className="text-right flex items-center gap-3 flex-shrink-0">
          <p className={`text-3xl font-bold ${isFailed ? 'text-[#EF4444]' : 'text-[#007AFF]'}`} style={{ fontFamily: 'Bebas Neue' }}>
            {pct}%
          </p>
          {isFailed && onRetry && (
            <button data-testid="match-retry-processing-btn" onClick={onRetry}
              className="px-3 py-2 text-[10px] font-bold tracking-wider uppercase bg-[#EF4444]/15 text-[#EF4444] hover:bg-[#EF4444]/25 border border-[#EF4444]/30 transition-colors">
              {completed.length > 0 ? 'Resume' : 'Retry'}
            </button>
          )}
        </div>
      </div>

      <div className="h-2 bg-[#0A0A0A] rounded-full overflow-hidden border border-white/5">
        <div className={`h-full rounded-full transition-all duration-500 ${isFailed ? 'bg-[#EF4444]' : 'bg-gradient-to-r from-[#007AFF] to-[#0A4DCE]'}`}
          style={{ width: `${pct}%` }}
          data-testid="match-processing-bar-fill" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
        {STEPS.map((step) => {
          const done = completed.includes(step.key);
          const isCurrent = current === step.key;
          const hasFailed = failed.includes(step.key);
          return (
            <div key={step.key} data-testid={`step-${step.key}`} className="flex items-center gap-2 text-[11px]">
              <StepIcon done={done} current={isCurrent} failed={hasFailed} />
              <span className={`tracking-wider font-medium ${
                done ? 'text-[#10B981]' : isCurrent ? 'text-[#007AFF]' : hasFailed ? 'text-[#EF4444]' : 'text-[#555]'
              }`}>
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {isActive && statusFeed.length > 0 && (
        <div data-testid="processing-status-feed" className="mt-5 bg-[#050505] border border-white/5 p-3 sm:p-4">
          <p className="text-[10px] tracking-[0.3em] uppercase font-bold text-[#A3A3A3] mb-2">
            Real-time status updates
          </p>
          <div ref={feedRef} className="space-y-1.5 max-h-32 overflow-y-auto pr-1 font-mono text-[11px] leading-snug">
            {statusFeed.map((entry, idx) => {
              const isLatest = idx === statusFeed.length - 1;
              return (
                <div key={entry.id} className={`flex items-center gap-2 ${isLatest ? 'text-[#7AA2D4]' : 'text-[#555]'}`}>
                  <span className="text-[#10B981]">›</span>
                  <span className="truncate">{entry.msg}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProcessingProgressBar;
