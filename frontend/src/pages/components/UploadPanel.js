import { useState, useCallback, useRef } from 'react';
import { VideoCamera, UploadSimple, ArrowsClockwise, CloudArrowUp, FileVideo, Package, CaretDown, ArrowSquareOut, X, WarningCircle, BellRinging, Bell } from '@phosphor-icons/react';
import CompressionCalculator from '../../components/CompressionCalculator';

const _formatBytes = (bytes) => {
  if (!bytes) return '';
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
};

const UploadInProgress = ({ uploadProgress, uploadStatus, selectedFile, notifyOnComplete, onToggleNotify }) => (
  <div className="max-w-md mx-auto">
    <div className="bg-[#0A0A0A] h-3 mb-3 rounded-full overflow-hidden">
      <div className="bg-[#007AFF] h-3 rounded-full" style={{ width: `${uploadProgress}%`, transition: 'width 0.3s ease' }} />
    </div>
    <p className="text-sm text-white font-medium mb-1" data-testid="upload-progress-pct">
      Uploading: {uploadProgress}%
    </p>
    {uploadStatus && <p className="text-xs text-[#A3A3A3]" data-testid="upload-status-text">{uploadStatus}</p>}
    {selectedFile && (
      <div className="mt-4 flex items-center justify-center gap-2 text-xs text-[#A3A3A3]" data-testid="upload-file-chip">
        <FileVideo size={14} className="text-[#007AFF]" />
        <span className="truncate max-w-[200px]">{selectedFile.name}</span>
        <span>·</span>
        <span>{_formatBytes(selectedFile.size)}</span>
      </div>
    )}
    {/* Notify-when-done toggle — fires a Web Notification via the service worker on finalize */}
    {onToggleNotify && (
      <button
        type="button"
        data-testid="notify-on-complete-toggle"
        onClick={onToggleNotify}
        className={`mt-5 w-full inline-flex items-center justify-center gap-2 px-3 py-2.5 text-[11px] font-bold tracking-wider uppercase border transition-colors ${
          notifyOnComplete
            ? 'border-[#10B981] bg-[#10B981]/10 text-[#10B981] hover:bg-[#10B981]/20'
            : 'border-white/15 text-[#A3A3A3] hover:text-white hover:border-white/30'
        }`}>
        {notifyOnComplete ? <BellRinging size={14} weight="fill" /> : <Bell size={14} weight="bold" />}
        {notifyOnComplete ? 'Notify me when done · ON' : 'Notify me when done'}
      </button>
    )}
    {onToggleNotify && (
      <p data-testid="notify-on-complete-hint" className="mt-1.5 text-[10px] text-[#666] leading-snug text-center">
        {notifyOnComplete
          ? 'Stay on this tab or background it — we\u2019ll buzz you when finalize completes.'
          : 'Get a browser notification so you can switch tabs / lock your screen.'}
      </p>
    )}
  </div>
);

const LARGE_FILE_THRESHOLD = 5 * 1024 * 1024 * 1024; // 5 GB — trigger compress nudge

const UploadPanel = ({ match, matchId, videoMeta, uploading, uploadProgress, uploadStatus,
  onVideoUpload, onShowDeleted, onViewAnalysis, onMatchInsights, onConfirmReupload, navigate,
  notifyOnComplete, onToggleNotify }) => {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [showCompressTip, setShowCompressTip] = useState(false);
  const [pendingLargeFile, setPendingLargeFile] = useState(null);
  const compressTipRef = useRef(null);

  const propagateUpload = useCallback((file) => {
    setSelectedFile(file);
    // Synthesize an event so the existing onVideoUpload handler keeps working
    onVideoUpload({ target: { files: [file] } });
  }, [onVideoUpload]);

  const handleFile = useCallback((file) => {
    if (!file) return;
    // For 5 GB+ files, intercept once and offer the compression path before kicking off the upload.
    if (file.size > LARGE_FILE_THRESHOLD) {
      setPendingLargeFile(file);
      setShowCompressTip(true);
      // Scroll the compress tip into view on next tick so the user sees the rationale
      setTimeout(() => {
        compressTipRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 50);
      return;
    }
    propagateUpload(file);
  }, [propagateUpload]);

  const handleProceedAnyway = () => {
    const file = pendingLargeFile;
    setPendingLargeFile(null);
    if (file) propagateUpload(file);
  };

  const handleCancelLargeFile = () => {
    setPendingLargeFile(null);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);
  const handleDragLeave = useCallback(() => setDragOver(false), []);

  if (!match.video_id) {
    return (
      <div
        data-testid="upload-dropzone"
        onDrop={!uploading ? handleDrop : undefined}
        onDragOver={!uploading ? handleDragOver : undefined}
        onDragLeave={!uploading ? handleDragLeave : undefined}
        className={`border-2 border-dashed p-12 text-center transition-colors ${
          dragOver ? 'border-[#007AFF] bg-[#007AFF]/5' : 'border-white/10 hover:border-white/20'
        }`}>
        {uploading ? (
          <>
            <CloudArrowUp size={64} className="text-[#007AFF] mx-auto mb-4 animate-pulse" />
            <h3 className="text-2xl font-bold mb-4" style={{ fontFamily: 'Bebas Neue' }}>Uploading Video</h3>
            <UploadInProgress
              uploadProgress={uploadProgress}
              uploadStatus={uploadStatus}
              selectedFile={selectedFile}
              notifyOnComplete={notifyOnComplete}
              onToggleNotify={onToggleNotify}
            />
          </>
        ) : (
          <>
            {/* Smart nudge — fired when user picks a file > 5 GB. Pre-empts the upload to surface the compression path. */}
            {pendingLargeFile && (
              <div
                data-testid="large-file-nudge"
                className="max-w-md mx-auto mb-6 bg-[#FBBF24]/10 border border-[#FBBF24]/40 p-4 text-left">
                <div className="flex items-start gap-3">
                  <WarningCircle size={20} weight="fill" className="text-[#FBBF24] mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-white">
                      Heads up — that file is {(pendingLargeFile.size / (1024 ** 3)).toFixed(1)} GB.
                    </p>
                    <p className="text-xs text-[#CFCFCF] mt-1 leading-relaxed">
                      Estimated upload: <strong className="text-white">~{Math.max(5, Math.round((pendingLargeFile.size / (1024 ** 3)) * 4))} min</strong>.
                      Compressing first with HandBrake typically shrinks raw film 3-4× → identical AI results, much faster upload.
                    </p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      <button
                        data-testid="large-file-nudge-show-tip"
                        onClick={() => {
                          setShowCompressTip(true);
                          setTimeout(() => compressTipRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
                        }}
                        className="inline-flex items-center gap-1.5 text-[11px] font-bold tracking-wider uppercase border border-[#FBBF24] bg-[#FBBF24]/10 text-[#FBBF24] hover:bg-[#FBBF24]/20 px-3 py-2 transition-colors">
                        <Package size={12} weight="bold" />
                        Show me how to compress
                      </button>
                      <button
                        data-testid="large-file-nudge-proceed"
                        onClick={handleProceedAnyway}
                        className="inline-flex items-center gap-1.5 text-[11px] font-bold tracking-wider uppercase border border-white/15 text-[#A3A3A3] hover:text-white hover:border-white/30 px-3 py-2 transition-colors">
                        Upload as-is
                      </button>
                    </div>
                  </div>
                  <button
                    data-testid="large-file-nudge-close"
                    onClick={handleCancelLargeFile}
                    aria-label="Cancel"
                    className="p-1 hover:bg-white/5 transition-colors flex-shrink-0">
                    <X size={14} className="text-[#666] hover:text-white" />
                  </button>
                </div>
              </div>
            )}

            <CloudArrowUp size={64} className={`mx-auto mb-4 ${dragOver ? 'text-[#007AFF]' : 'text-[#A3A3A3]'}`} />
            <h3 className="text-2xl font-bold mb-2 uppercase tracking-wider" style={{ fontFamily: 'Bebas Neue' }}>
              Drag &amp; Drop Video Files Here
            </h3>
            <p className="text-[#A3A3A3] mb-6 text-sm">
              or{' '}
              <label className="text-[#007AFF] hover:underline cursor-pointer underline-offset-2"
                data-testid="upload-browse-link">
                click to browse
                <input type="file" accept="video/*"
                  onChange={(e) => handleFile(e.target.files?.[0])}
                  className="hidden" />
              </label>
              {' '}— MP4, MOV, AVI up to 20 GB
            </p>
            <label data-testid="upload-video-btn"
              className="inline-flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors cursor-pointer">
              <UploadSimple size={20} weight="bold" />
              Select Video File
              <input type="file" accept="video/*"
                onChange={(e) => handleFile(e.target.files?.[0])} className="hidden" />
            </label>
            <button data-testid="show-deleted-link" onClick={onShowDeleted}
              className="block mt-6 text-xs text-[#666] hover:text-[#A3A3A3] underline underline-offset-2 mx-auto">
              Recover a recently deleted video
            </button>

            {/* Compression tip — discoverable expander for users uploading raw 9-15GB match film */}
            <div ref={compressTipRef} className="mt-8 pt-5 border-t border-white/5 max-w-md mx-auto text-left">
              <button
                data-testid="compress-tip-toggle"
                onClick={() => setShowCompressTip((v) => !v)}
                className="flex items-center justify-between gap-2 w-full text-[11px] tracking-wider uppercase font-bold text-[#A3A3A3] hover:text-white transition-colors group">
                <span className="flex items-center gap-2">
                  <Package size={14} weight="bold" className="text-[#FBBF24]" />
                  Got a 5 GB+ file? Compress it first
                </span>
                <CaretDown
                  size={14}
                  weight="bold"
                  className={`transition-transform ${showCompressTip ? 'rotate-180' : ''}`}
                />
              </button>

              {showCompressTip && (
                <div data-testid="compress-tip-panel" className="mt-3 bg-[#FBBF24]/5 border border-[#FBBF24]/20 p-4">
                  <p className="text-xs text-[#CFCFCF] leading-relaxed mb-3">
                    Raw match film from a sideline cam is usually <strong className="text-white">9-15 GB</strong>. Soccer Scout 11
                    downscales every video to <strong className="text-white">240p / 8 fps</strong> before AI analysis — so a 12 GB raw
                    file and a 3 GB compressed file yield <strong className="text-white">identical</strong> heatmaps, timeline markers,
                    and highlight reels. Compressing first means a 3-4× faster upload with zero quality loss.
                  </p>
                  <p className="text-[10px] tracking-[0.15em] uppercase text-[#FBBF24] font-bold mb-2">Recommended workflow</p>
                  <ol className="text-xs text-[#CFCFCF] leading-relaxed space-y-1.5 list-decimal list-inside marker:text-[#FBBF24] marker:font-bold">
                    <li>
                      Install{' '}
                      <a
                        href="https://handbrake.fr/downloads.php"
                        target="_blank"
                        rel="noopener noreferrer"
                        data-testid="handbrake-link"
                        className="text-[#FBBF24] hover:underline inline-flex items-center gap-0.5">
                        HandBrake <ArrowSquareOut size={10} weight="bold" />
                      </a>{' '}
                      (free, Mac / Windows / Linux).
                    </li>
                    <li>Open your match video, then pick preset <strong className="text-white">Fast 1080p30</strong>.</li>
                    <li>
                      Video tab → set <strong className="text-white">Constant Quality</strong> to <strong className="text-white">22</strong>{' '}
                      (lower is bigger; 22 is the sweet spot for sideline cam film).
                    </li>
                    <li>Start Encode. A 12 GB file becomes ~3 GB in 10-15 min on a modern laptop.</li>
                    <li>Drag the smaller file here and let Soccer Scout 11 do the rest.</li>
                  </ol>
                  <p className="text-[10px] text-[#A3A3A3] mt-3 italic">
                    Already happy with your file? Skip this — uploads up to 20 GB work fine, just slower.
                  </p>

                  <CompressionCalculator initialSizeBytes={pendingLargeFile?.size || selectedFile?.size || 0} />
                </div>
              )}
            </div>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="video-status-bar">
      <div className="flex items-center gap-2 text-[#39FF14]">
        <VideoCamera size={24} />
        <span className="font-bold tracking-wider uppercase">Video Uploaded</span>
      </div>
      {videoMeta?.processing_status && videoMeta.processing_status !== 'none' && (
        <span data-testid="processing-status-chip"
          className={`text-[10px] tracking-[0.2em] uppercase font-bold px-3 py-1 ${
            videoMeta.processing_status === 'completed' ? 'bg-[#10B981]/15 text-[#10B981]' :
            videoMeta.processing_status === 'failed' ? 'bg-[#EF4444]/15 text-[#EF4444]' :
            'bg-[#FBBF24]/15 text-[#FBBF24]'
          }`}>
          {videoMeta.processing_status === 'completed' ? 'AI ready' :
           videoMeta.processing_status === 'failed' ? 'Processing failed' :
           `Processing… ${videoMeta.processing_progress || 0}%`}
        </span>
      )}
      <button data-testid="view-analysis-btn" onClick={() => navigate(`/video/${match.video_id}`)}
        className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors">
        View Analysis
      </button>
      <button data-testid="match-insights-btn" onClick={() => navigate(`/match/${matchId}/insights`)}
        className="flex items-center gap-2 bg-gradient-to-r from-[#A855F7] to-[#FBBF24] hover:opacity-90 text-black px-5 py-3 font-bold tracking-wider uppercase text-xs transition-opacity">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L9.91 8.26L2 9.27L7.91 14.14L6.18 22L12 18.27L17.82 22L16.09 14.14L22 9.27L14.09 8.26L12 2Z"/>
        </svg>
        AI Insights
      </button>
      <button data-testid="reupload-video-btn" onClick={onConfirmReupload}
        className="flex items-center gap-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-4 py-3 font-bold tracking-wider uppercase text-xs transition-colors"
        title="Delete this video and upload a new one. Clips and AI analysis will be removed.">
        <ArrowsClockwise size={14} weight="bold" /> Replace Video
      </button>
    </div>
  );
};

export default UploadPanel;
