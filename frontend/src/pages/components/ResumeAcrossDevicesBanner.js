import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { CaretRight, Laptop, Clock, X, Stack } from '@phosphor-icons/react';
import BulkResumeModal from './BulkResumeModal';

/**
 * iter84 — Resume Across Devices banner.
 * iter85 — Per-row Dismiss buttons for old/abandoned sessions.
 *
 * Coach starts an 800 MB upload from their laptop at the field. Connection
 * drops at 60%. They drive home, open the app on their phone, and instead
 * of digging through matches to find which one had the upload, they see a
 * banner: "1 upload paused — finish on this device". Tap → match page →
 * the orange match-level resume banner appears → re-pick the same file on
 * the phone → upload resumes from chunk 60%+1.
 *
 * Powered by GET /api/me/pending-uploads. Chunks are durable across pod
 * restarts (iter83 persistent PV fallback + background migration to object
 * storage), so the resume is safe from the original upload's perspective.
 *
 * iter85: Each row has an X dismiss button. Dismissing a session hides it
 * from the banner forever AND best-effort frees the persistent fallback
 * chunks on /app so disk doesn't grow unbounded across abandoned uploads.
 */
const ResumeAcrossDevicesBanner = () => {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [dismissing, setDismissing] = useState(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);

  const refetch = () => {
    axios.get(`${API}/me/pending-uploads`, { headers: getAuthHeader() })
      .then((res) => { setSessions(res.data?.sessions || []); setLoaded(true); })
      .catch(() => setLoaded(true));
  };

  useEffect(() => {
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDismiss = async (e, uploadId) => {
    e.stopPropagation();  // don't navigate when clicking the X
    if (dismissing.has(uploadId)) return;
    setDismissing((prev) => new Set([...prev, uploadId]));
    try {
      await axios.delete(`${API}/me/pending-uploads/${uploadId}`, { headers: getAuthHeader() });
      setSessions((prev) => prev.filter((s) => s.upload_id !== uploadId));
    } catch (err) {
      console.error('Failed to dismiss upload:', err);
      // Roll back the "in flight" state so user can retry
      setDismissing((prev) => {
        const next = new Set(prev);
        next.delete(uploadId);
        return next;
      });
    }
  };

  if (!loaded || sessions.length === 0) return null;

  const total = sessions.length;
  const first = sessions[0];
  const headline = total === 1
    ? '1 upload paused — finish on this device'
    : `${total} uploads paused — finish on this device`;
  const sub = total === 1
    ? `${first.filename} (${first.file_size_gb} GB) — ${first.progress_pct}% delivered`
    : `Latest: ${first.filename} (${first.progress_pct}%) and ${total - 1} more`;

  return (
    <>
    <div data-testid="resume-across-devices-banner"
      className="mb-6 bg-gradient-to-r from-[#0A1A2E] via-[#0A0F1A] to-[#0A0A0A] border border-[#007AFF]/40">
      <div className="flex items-stretch">
        <button data-testid="resume-across-devices-toggle"
          onClick={() => total === 1 ? navigate(`/match/${first.match_id}`) : setExpanded(!expanded)}
          className="flex-1 flex items-start gap-4 px-5 py-4 text-left hover:bg-[#007AFF]/5 transition-colors">
          <div className="w-11 h-11 bg-[#007AFF]/15 border border-[#007AFF]/30 flex items-center justify-center flex-shrink-0">
            <Laptop size={22} weight="bold" className="text-[#007AFF]" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#007AFF] mb-1">
              Continue where you left off
            </div>
            <div className="text-base font-bold text-white truncate">{headline}</div>
            <div className="text-xs text-[#A3A3A3] mt-0.5 truncate">{sub}</div>
          </div>
          <CaretRight size={20} weight="bold"
            className={`text-[#007AFF] flex-shrink-0 mt-2 transition-transform ${
              total > 1 && expanded ? 'rotate-90' : ''
            }`} />
        </button>
        {/* iter92: Resume All button for the multi-session case so the user
            can finish all pending uploads in one go via a single multi-file
            picker, instead of navigating to N different matches. */}
        {total > 1 && (
          <button data-testid="resume-all-btn"
            onClick={(e) => { e.stopPropagation(); setBulkOpen(true); }}
            title="Resume all paused uploads at once via a single multi-file picker"
            className="px-4 border-l border-[#007AFF]/15 flex items-center gap-2 text-[#007AFF] text-xs font-bold tracking-wide uppercase hover:bg-[#007AFF]/10 transition-colors flex-shrink-0">
            <Stack size={16} weight="bold" />
            <span className="hidden sm:inline">Resume all</span>
          </button>
        )}
        {/* Inline dismiss for the single-session case — otherwise the user
            has to expand a 1-row "list" just to find the X. */}
        {total === 1 && (
          <button
            data-testid={`dismiss-session-${first.upload_id}`}
            onClick={(e) => handleDismiss(e, first.upload_id)}
            disabled={dismissing.has(first.upload_id)}
            title="Dismiss — hide this from the banner and free local chunk files"
            className="px-4 border-l border-[#007AFF]/15 text-[#A3A3A3] hover:text-white hover:bg-white/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
            <X size={18} weight="bold" />
          </button>
        )}
      </div>

      {total > 1 && expanded && (
        <div className="border-t border-[#007AFF]/15" data-testid="resume-across-devices-list">
          {sessions.map((s) => (
            <div
              key={s.upload_id}
              className="flex items-stretch border-b border-[#007AFF]/10 last:border-b-0 hover:bg-[#007AFF]/5 transition-colors">
              <button
                data-testid={`resume-session-${s.upload_id}`}
                onClick={() => navigate(`/match/${s.match_id}`)}
                className="flex-1 px-5 py-3 flex items-center gap-3 text-left">
                <Clock size={16} className="text-[#A3A3A3] flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-bold text-white truncate">{s.match_label}</div>
                  <div className="text-xs text-[#A3A3A3] truncate">
                    {s.filename} · {s.file_size_gb} GB · {s.chunks_received}/{s.total_chunks} chunks ({s.progress_pct}%)
                  </div>
                </div>
                <CaretRight size={14} className="text-[#A3A3A3] flex-shrink-0" />
              </button>
              <button
                data-testid={`dismiss-session-${s.upload_id}`}
                onClick={(e) => handleDismiss(e, s.upload_id)}
                disabled={dismissing.has(s.upload_id)}
                title="Dismiss — hide this from the banner and free local chunk files"
                className="px-3 border-l border-[#007AFF]/10 text-[#A3A3A3] hover:text-white hover:bg-white/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                <X size={14} weight="bold" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
    <BulkResumeModal
      open={bulkOpen}
      onClose={() => setBulkOpen(false)}
      sessions={sessions}
      onAllComplete={() => { refetch(); }}
    />
    </>
  );
};

export default ResumeAcrossDevicesBanner;
