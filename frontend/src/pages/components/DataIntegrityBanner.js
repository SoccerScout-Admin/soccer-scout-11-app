const DataIntegrityBanner = ({ videoMetadata }) => {
  if (!videoMetadata || !videoMetadata.data_integrity || videoMetadata.data_integrity === 'full') return null;
  const isUnavailable = videoMetadata.data_integrity === 'unavailable';
  const pct = videoMetadata.chunks_total
    ? Math.round(videoMetadata.chunks_available / videoMetadata.chunks_total * 100)
    : 0;
  return (
    <div data-testid="data-integrity-warning" className="bg-[#1A1A0A] border border-[#FFB800]/30 rounded-lg px-6 py-4 mb-6">
      <div className="flex items-center gap-3">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FFB800" strokeWidth="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <div>
          <p className="text-sm font-medium text-[#FFB800]">
            {isUnavailable ? 'Video data unavailable' : 'Partial video data'}
          </p>
          <p className="text-xs text-[#888] mt-0.5">
            {isUnavailable
              ? 'All video chunks were lost during a server restart. Please re-upload the video.'
              : `Only ${videoMetadata.chunks_available} of ${videoMetadata.chunks_total} chunks available (${pct}%). Video may stop playing early. Re-upload for full playback.`}
          </p>
        </div>
      </div>
    </div>
  );
};

export default DataIntegrityBanner;
