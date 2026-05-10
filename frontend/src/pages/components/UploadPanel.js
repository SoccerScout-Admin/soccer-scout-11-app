import { useState, useCallback } from 'react';
import { VideoCamera, UploadSimple, ArrowsClockwise, CloudArrowUp, FileVideo } from '@phosphor-icons/react';

const _formatBytes = (bytes) => {
  if (!bytes) return '';
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
};

const UploadInProgress = ({ uploadProgress, uploadStatus, selectedFile }) => (
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
  </div>
);

const UploadPanel = ({ match, matchId, videoMeta, uploading, uploadProgress, uploadStatus,
  onVideoUpload, onShowDeleted, onViewAnalysis, onMatchInsights, onConfirmReupload, navigate }) => {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);

  const handleFile = useCallback((file) => {
    if (!file) return;
    setSelectedFile(file);
    // Synthesize an event so the existing onVideoUpload handler keeps working
    onVideoUpload({ target: { files: [file] } });
  }, [onVideoUpload]);

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
            <UploadInProgress uploadProgress={uploadProgress} uploadStatus={uploadStatus} selectedFile={selectedFile} />
          </>
        ) : (
          <>
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
              {' '}— MP4, MOV, AVI up to 5 GB
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
