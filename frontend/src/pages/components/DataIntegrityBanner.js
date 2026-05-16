import { useEffect, useState } from 'react';

/**
 * Banner that surfaces upload-integrity problems.
 *
 * Two visual states:
 *  - WARNING (amber): integrity != "full" but processing hasn't been stuck.
 *    Informational — playback may end early, but the user might just want to
 *    scrub the clip-able portion and move on.
 *  - ERROR (red): integrity != "full" AND
 *      (a) processing already failed, OR
 *      (b) processing has been at progress=0 for >120s.
 *    AI analysis literally cannot complete on a partial file. We escalate to
 *    a red callout with a one-click "DELETE & RE-UPLOAD" CTA so the recovery
 *    path is obvious instead of leaving the user staring at an infinite
 *    0% spinner (real production bug 2026-05-16, video 48823490, 980/991).
 */
const DataIntegrityBanner = ({ videoMetadata, processingStatus, onReupload }) => {
  const [stuckAtZero, setStuckAtZero] = useState(false);

  // Track how long we've been at progress=0 in queued/processing state. After
  // 120s with no movement we treat it as effectively stuck and escalate.
  useEffect(() => {
    if (!processingStatus) return;
    const status = processingStatus.processing_status;
    const progress = processingStatus.processing_progress ?? 0;
    const isPending = status === 'queued' || status === 'processing';
    if (!isPending || progress > 0) {
      setStuckAtZero(false);
      return;
    }
    const t = setTimeout(() => setStuckAtZero(true), 120_000);
    return () => clearTimeout(t);
  }, [processingStatus]);

  if (!videoMetadata || !videoMetadata.data_integrity || videoMetadata.data_integrity === 'full') return null;

  const isUnavailable = videoMetadata.data_integrity === 'unavailable';
  const pct = videoMetadata.chunks_total
    ? Math.round(videoMetadata.chunks_available / videoMetadata.chunks_total * 100)
    : 0;

  // Detect the "AI can't possibly complete" cases. Backend now also marks
  // these as failed on resume (iter70), but we still escalate client-side
  // when failure_state lags or processing hasn't run yet.
  const processingFailed = processingStatus?.processing_status === 'failed';
  const errorBecauseIncompleteUpload =
    typeof processingStatus?.processing_error === 'string'
    && processingStatus.processing_error.toLowerCase().includes('upload incomplete');
  const elevated = isUnavailable || processingFailed || errorBecauseIncompleteUpload || stuckAtZero;

  if (!elevated) {
    // Amber warning — playback-only impact, no AI escalation yet.
    return (
      <div data-testid="data-integrity-warning"
        className="bg-[#1A1A0A] border border-[#FFB800]/30 rounded-lg px-6 py-4 mb-6">
        <div className="flex items-center gap-3">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FFB800" strokeWidth="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <div>
            <p className="text-sm font-medium text-[#FFB800]">Partial video data</p>
            <p className="text-xs text-[#888] mt-0.5">
              Only {videoMetadata.chunks_available} of {videoMetadata.chunks_total} chunks available ({pct}%). Video may stop playing early. Re-upload for full playback.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Red CTA — AI analysis is permanently blocked until the user re-uploads.
  const subtitle = isUnavailable
    ? 'All video chunks were lost during a server restart. The video file is gone and AI analysis cannot run.'
    : `Only ${videoMetadata.chunks_available} of ${videoMetadata.chunks_total} chunks available (${pct}%). AI analysis can't run on a partial file — every retry will hit the same incomplete-data wall.`;

  return (
    <div data-testid="data-integrity-error"
      className="bg-[#1A0A0A] border border-[#EF4444]/40 rounded-lg px-6 py-5 mb-6">
      <div className="flex items-start gap-4">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2"
          className="flex-shrink-0 mt-0.5">
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <div className="flex-1">
          <p className="text-sm font-bold text-[#EF4444] tracking-wider uppercase">Re-upload required</p>
          <p className="text-xs text-[#A3A3A3] mt-1 leading-relaxed">{subtitle}</p>
          <p className="text-xs text-[#666] mt-2">
            The match, your roster, and any clips you've already created stay intact. Only the video file is replaced.
          </p>
        </div>
        {onReupload && (
          <button data-testid="data-integrity-reupload-btn" onClick={onReupload}
            className="flex-shrink-0 bg-[#EF4444] hover:bg-[#DC2626] text-white text-xs font-bold tracking-wider uppercase px-4 py-2 transition-colors">
            Delete &amp; Re-upload
          </button>
        )}
      </div>
    </div>
  );
};

export default DataIntegrityBanner;
