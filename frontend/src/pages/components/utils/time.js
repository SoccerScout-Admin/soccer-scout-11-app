/**
 * Format seconds → "M:SS" used across video-analysis components.
 */
export const formatTime = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
};
