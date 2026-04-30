import LiveCoachingMic from './LiveCoachingMic';
import { formatTime } from './utils/time';

const VideoToolbar = ({
  videoId,
  currentTimestamp,
  videoDuration,
  clipFormData,
  setClipFormData,
  setShowClipForm,
  annotationMode,
  setAnnotationMode,
  setShowAnnotationForm,
  onAnnotationAdded,
  showTrimPanel,
  setShowTrimPanel,
  setTrimStart,
  setTrimEnd,
}) => {
  const modes = [['note', 'Note'], ['tactical', 'Tactical'], ['key_moment', 'Key Moment']];
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="flex items-center gap-1.5 bg-white/5 rounded-lg px-3 py-2">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#888" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
        </svg>
        <span className="text-sm text-white font-mono">{formatTime(currentTimestamp)}</span>
      </div>
      <button data-testid="create-clip-btn"
        onClick={() => { setShowClipForm(true); setClipFormData({ ...clipFormData, start_time: currentTimestamp, end_time: currentTimestamp + 10 }); }}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#007AFF] text-white text-xs font-medium hover:bg-[#0066DD] transition-colors">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12"/>
        </svg>
        Create Clip
      </button>
      {modes.map(([mode, label]) => (
        <button key={mode} data-testid={`${mode}-tool-btn`}
          onClick={() => { setAnnotationMode(mode); setShowAnnotationForm(true); }}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
            annotationMode === mode ? 'bg-[#007AFF] text-white' : 'bg-white/5 text-[#888] hover:text-white hover:bg-white/10'
          }`}>
          {label}
        </button>
      ))}
      <div className="hidden sm:block">
        <LiveCoachingMic
          videoId={videoId}
          videoCurrentTime={currentTimestamp}
          isMobile={false}
          onAnnotationAdded={onAnnotationAdded}
        />
      </div>
      <div className="ml-auto">
        <button data-testid="trim-analyze-btn"
          onClick={() => { setShowTrimPanel(!showTrimPanel); setTrimStart(0); setTrimEnd(Math.floor(videoDuration)); }}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
            showTrimPanel ? 'bg-[#A855F7] text-white' : 'bg-white/5 text-[#888] hover:text-white hover:bg-white/10'
          }`}>
          Trim &amp; Analyze
        </button>
      </div>
    </div>
  );
};

export default VideoToolbar;
