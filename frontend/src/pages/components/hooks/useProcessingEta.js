import { useState, useEffect } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../../App';

/**
 * Returns an ETA string ("~3 min remaining") for an in-flight video
 * processing run. Strategy:
 *   - progress < 10% or missing started_at → use historical avg from
 *     GET /api/videos/processing-eta-stats
 *   - progress >= 10% → extrapolate from elapsed time and current progress:
 *     estimatedTotal = elapsed / (progress/100); remaining = estimatedTotal - elapsed
 *   - blend the two when we have both signals (70% historical + 30% live early on,
 *     crossfading to 100% live by 60% progress) for smoother numbers.
 *
 * Returns `null` when we can't make a reasonable estimate.
 *
 * @param {object} videoMeta — same shape as /api/videos/{id}/processing-status
 * @returns {string|null} human-readable ETA
 */
export const useProcessingEta = (videoMeta) => {
  const [avgSeconds, setAvgSeconds] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/videos/processing-eta-stats`, { headers: getAuthHeader() })
      .then((res) => { if (!cancelled) setAvgSeconds(res.data.avg_seconds); })
      .catch(() => { /* silent — fall back to live extrapolation */ });
    return () => { cancelled = true; };
  }, []);

  // Keep 'now' fresh so the ETA ticks down visually every 3s
  useEffect(() => {
    const status = videoMeta?.processing_status;
    if (status !== 'processing' && status !== 'queued') return;
    const id = setInterval(() => setNow(Date.now()), 3000);
    return () => clearInterval(id);
  }, [videoMeta?.processing_status]);

  if (!videoMeta) return null;
  const status = videoMeta.processing_status;
  if (status !== 'processing' && status !== 'queued') return null;

  const progress = Math.max(0, Math.min(100, videoMeta.processing_progress || 0));
  const startedAt = videoMeta.processing_started_at ? new Date(videoMeta.processing_started_at).getTime() : null;
  const elapsed = startedAt ? Math.max(0, (now - startedAt) / 1000) : null;

  let remainingSec = null;

  // 1. Live extrapolation (only valid once we have meaningful progress)
  let liveRemaining = null;
  if (elapsed !== null && progress >= 10) {
    const estimatedTotal = elapsed / (progress / 100);
    liveRemaining = Math.max(0, estimatedTotal - elapsed);
  }

  // 2. Historical-average remaining
  let histRemaining = null;
  if (avgSeconds) {
    histRemaining = Math.max(0, avgSeconds * (1 - progress / 100));
  }

  if (liveRemaining !== null && histRemaining !== null) {
    // Crossfade: at progress=10% use 80% historical / 20% live; at progress=60% use 100% live
    const liveWeight = Math.max(0, Math.min(1, (progress - 10) / 50));
    remainingSec = liveRemaining * liveWeight + histRemaining * (1 - liveWeight);
  } else {
    remainingSec = liveRemaining ?? histRemaining;
  }

  if (remainingSec === null || !isFinite(remainingSec)) return null;

  return _humanize(remainingSec);
};

const _humanize = (seconds) => {
  if (seconds < 20) return '< 20 sec remaining';
  if (seconds < 90) return `~${Math.round(seconds)} sec remaining`;
  const minutes = seconds / 60;
  if (minutes < 10) {
    const rounded = Math.round(minutes * 2) / 2; // nearest 0.5
    return `~${rounded} min remaining`;
  }
  return `~${Math.round(minutes)} min remaining`;
};
