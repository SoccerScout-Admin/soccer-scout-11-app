import { forwardRef } from 'react';

const MARKER_COLORS = {
  goal: '#FFD700',
  shot: '#FF6B35',
  save: '#4ADE80',
  foul: '#EF4444',
  card: '#EF4444',
  substitution: '#A855F7',
  tactical: '#007AFF',
  chance: '#FFB800',
};

const LEGEND_ENTRIES = [
  ['goal', '#FFD700', 'Goals'],
  ['shot', '#FF6B35', 'Shots'],
  ['save', '#4ADE80', 'Saves'],
  ['foul', '#EF4444', 'Fouls'],
  ['tactical', '#007AFF', 'Tactical'],
  ['chance', '#FFB800', 'Chances'],
];

const formatTime = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
};

/**
 * Video player + AI timeline markers strip + markers legend.
 * forwardRef so the parent retains direct control over playback (currentTime, play, pause).
 */
const VideoPlayerWithMarkers = forwardRef(function VideoPlayerWithMarkers(
  { videoSrc, markers, videoDuration, onTimeUpdate, onLoadedMetadata, onSeek },
  ref
) {
  return (
    <>
      <div className="bg-black rounded-lg overflow-hidden relative">
        <video
          ref={ref}
          data-testid="video-player"
          controls
          className="w-full aspect-video"
          src={videoSrc}
          preload="auto"
          onTimeUpdate={(e) => onTimeUpdate(e.target.currentTime)}
          onLoadedMetadata={(e) => onLoadedMetadata(e.target.duration || 0)}
        />
        {/* AI Timeline Markers Bar */}
        {markers.length > 0 && videoDuration > 0 && (
          <div
            data-testid="timeline-markers-bar"
            className="absolute bottom-[52px] left-0 right-0 h-5 pointer-events-none z-10 px-[12px]"
          >
            {markers.map((m) => {
              const pct = (m.time / videoDuration) * 100;
              if (pct < 0 || pct > 100) return null;
              const color = MARKER_COLORS[m.type] || '#888';
              return (
                <button
                  key={m.id}
                  data-testid={`marker-${m.id}`}
                  title={`${formatTime(m.time)} — ${m.label}`}
                  onClick={() => onSeek(m.time)}
                  style={{ left: `${pct}%`, backgroundColor: color }}
                  className="absolute top-0 w-2.5 h-5 -translate-x-1/2 pointer-events-auto cursor-pointer hover:scale-y-125 transition-transform opacity-90 hover:opacity-100"
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Markers Legend */}
      {markers.length > 0 && (
        <div
          data-testid="markers-legend"
          className="flex items-center gap-3 flex-wrap bg-white/[0.03] rounded-lg px-3 py-2"
        >
          <span className="text-[10px] text-[#666] uppercase tracking-wider">AI Markers:</span>
          {LEGEND_ENTRIES.map(([type, color, label]) => {
            const count = markers.filter((m) => m.type === type).length;
            if (count === 0) return null;
            return (
              <span key={type} className="flex items-center gap-1 text-[10px] text-[#AAA]">
                <span className="w-2 h-2 rounded-sm inline-block" style={{ backgroundColor: color }} />
                {label} ({count})
              </span>
            );
          })}
        </div>
      )}
    </>
  );
});

export default VideoPlayerWithMarkers;
