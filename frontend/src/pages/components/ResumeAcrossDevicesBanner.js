import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { CaretRight, Laptop, Clock } from '@phosphor-icons/react';

/**
 * iter84 — Resume Across Devices banner.
 *
 * Coach starts an 800 MB upload from their laptop at the field. Connection
 * drops at 60%. They drive home, open the app on their phone, and instead
 * of digging through matches to find which one had the upload, they see a
 * banner: "1 upload paused — finish on this device". Tap → match page →
 * the orange match-level resume banner appears → re-pick the same file on
 * the phone → upload resumes from chunk 60%+1.
 *
 * Powered by GET /api/me/pending-uploads (post-iter84). Chunks are
 * durable across pod restarts (iter83 persistent PV fallback + background
 * migration to object storage), so the resume is safe from the original
 * upload's perspective.
 */
const ResumeAcrossDevicesBanner = () => {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/me/pending-uploads`, { headers: getAuthHeader() })
      .then((res) => {
        if (cancelled) return;
        setSessions(res.data?.sessions || []);
        setLoaded(true);
      })
      .catch(() => { if (!cancelled) setLoaded(true); /* silent — banner just hides */ });
    return () => { cancelled = true; };
  }, []);

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
    <div data-testid="resume-across-devices-banner"
      className="mb-6 bg-gradient-to-r from-[#0A1A2E] via-[#0A0F1A] to-[#0A0A0A] border border-[#007AFF]/40">
      <button data-testid="resume-across-devices-toggle"
        onClick={() => total === 1 ? navigate(`/match/${first.match_id}`) : setExpanded(!expanded)}
        className="w-full flex items-start gap-4 px-5 py-4 text-left hover:bg-[#007AFF]/5 transition-colors">
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

      {total > 1 && expanded && (
        <div className="border-t border-[#007AFF]/15" data-testid="resume-across-devices-list">
          {sessions.map((s) => (
            <button
              key={s.upload_id}
              data-testid={`resume-session-${s.upload_id}`}
              onClick={() => navigate(`/match/${s.match_id}`)}
              className="w-full px-5 py-3 flex items-center gap-3 text-left hover:bg-[#007AFF]/5 transition-colors border-b border-[#007AFF]/10 last:border-b-0">
              <Clock size={16} className="text-[#A3A3A3] flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-bold text-white truncate">{s.match_label}</div>
                <div className="text-xs text-[#A3A3A3] truncate">
                  {s.filename} · {s.file_size_gb} GB · {s.chunks_received}/{s.total_chunks} chunks ({s.progress_pct}%)
                </div>
              </div>
              <CaretRight size={14} className="text-[#A3A3A3] flex-shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default ResumeAcrossDevicesBanner;
