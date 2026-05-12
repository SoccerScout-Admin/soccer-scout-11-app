/**
 * DiskPressureBanner
 * -------------------
 * Polls /api/health every 60s. When the backend's circuit breaker is engaged
 * (uploads_blocked === true), renders a discreet red strip at the top of the
 * authenticated app explaining what's happening and that already-in-flight
 * uploads will resume. Auto-hides when pressure clears.
 *
 * Mounted globally inside BrowserRouter so coaches see it wherever they are —
 * including the Dashboard before they invest time creating a new match.
 */
import { useEffect, useState, useRef } from 'react';
import axios from 'axios';
import { API } from '../App';
import { useLocation } from 'react-router-dom';
import { Warning, X } from '@phosphor-icons/react';

const POLL_INTERVAL_MS = 60_000;
const SUPPRESS_KEY = 'disk_pressure_dismissed_until';
const SUPPRESS_DURATION_MS = 5 * 60 * 1000; // 5 min — re-shows soon enough to remain useful

// Routes where the banner shouldn't render — public/share routes & auth pages.
const PUBLIC_ROUTE_PREFIXES = ['/auth', '/reset-password', '/shared', '/clip', '/clips', '/reel', '/match-recap'];

const DiskPressureBanner = () => {
  const [info, setInfo] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const timerRef = useRef(null);
  const location = useLocation();

  // Skip the public/auth surface — coaches don't have an upload action there.
  const isPublic = PUBLIC_ROUTE_PREFIXES.some((p) => location.pathname.startsWith(p));

  useEffect(() => {
    if (isPublic) return undefined;

    // Honor a recent user dismissal
    try {
      const until = parseInt(localStorage.getItem(SUPPRESS_KEY) || '0', 10);
      if (until && Date.now() < until) {
        setDismissed(true);
      } else {
        localStorage.removeItem(SUPPRESS_KEY);
      }
    } catch {
      // ignore quota / private-mode errors
    }

    let cancelled = false;
    const tick = async () => {
      try {
        const res = await axios.get(`${API}/health`, { timeout: 8000 });
        if (!cancelled) setInfo(res.data);
      } catch {
        // Network blip — keep previous state, don't crash the banner
      }
    };
    tick();
    timerRef.current = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPublic]);

  const handleDismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(SUPPRESS_KEY, String(Date.now() + SUPPRESS_DURATION_MS));
    } catch {
      // ignore
    }
  };

  if (isPublic) return null;
  if (!info?.disk?.uploads_blocked) return null;
  if (dismissed) return null;

  const usedPct = info.disk.used_pct ?? '—';
  const freeGB = info.disk.free_gb ?? '—';

  return (
    <div
      data-testid="disk-pressure-banner"
      role="alert"
      className="fixed top-0 inset-x-0 z-[150] bg-[#EF4444] text-white shadow-lg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2.5 flex items-center gap-3">
        <Warning size={18} weight="fill" className="flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-xs sm:text-sm font-bold leading-tight">
            Heavy server load — new uploads paused for a few minutes.
          </p>
          <p className="text-[11px] sm:text-xs opacity-90 leading-snug">
            Match film already on the way will keep uploading from where it stopped.
            <span className="hidden sm:inline ml-2 font-mono opacity-70">
              ({usedPct}% used · {freeGB} GB free)
            </span>
          </p>
        </div>
        <button
          data-testid="disk-pressure-banner-dismiss"
          onClick={handleDismiss}
          aria-label="Dismiss for 5 minutes"
          className="p-1.5 hover:bg-white/15 transition-colors flex-shrink-0">
          <X size={14} weight="bold" />
        </button>
      </div>
    </div>
  );
};

export default DiskPressureBanner;
