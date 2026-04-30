import { VideoCamera, UploadSimple, ArrowsClockwise } from '@phosphor-icons/react';

const UploadInProgress = ({ uploadProgress, uploadStatus }) => (
  <div className="max-w-md mx-auto">
    <div className="bg-[#0A0A0A] h-3 mb-3 rounded-full overflow-hidden">
      <div className="bg-[#007AFF] h-3 rounded-full" style={{ width: `${uploadProgress}%`, transition: 'width 0.3s ease' }} />
    </div>
    <p className="text-sm text-white font-medium mb-1">{uploadProgress}%</p>
    {uploadStatus && <p className="text-xs text-[#A3A3A3]" data-testid="upload-status-text">{uploadStatus}</p>}
  </div>
);

const UploadPanel = ({ match, matchId, videoMeta, uploading, uploadProgress, uploadStatus,
  onVideoUpload, onShowDeleted, onViewAnalysis, onMatchInsights, onConfirmReupload, navigate }) => {
  if (!match.video_id) {
    return (
      <div className="border-2 border-dashed border-white/10 p-12 text-center">
        <VideoCamera size={64} className="text-[#A3A3A3] mx-auto mb-4" />
        <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Upload Match Video</h3>
        <p className="text-[#A3A3A3] mb-6">Upload footage to enable AI analysis and annotations</p>
        {uploading ? (
          <UploadInProgress uploadProgress={uploadProgress} uploadStatus={uploadStatus} />
        ) : (
          <label data-testid="upload-video-btn"
            className="inline-flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors cursor-pointer">
            <UploadSimple size={24} weight="bold" />
            Select Video File
            <input type="file" accept="video/*" onChange={onVideoUpload} className="hidden" />
          </label>
        )}
        {!uploading && (
          <button data-testid="show-deleted-link" onClick={onShowDeleted}
            className="block mt-4 text-xs text-[#666] hover:text-[#A3A3A3] underline underline-offset-2">
            Recover a recently deleted video
          </button>
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
