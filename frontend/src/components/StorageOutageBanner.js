import { useEffect, useState } from 'react';
import axios from 'axios';
import { API } from '../App';
import { WarningCircle } from '@phosphor-icons/react';

/**
 * iter91 — Global Object Storage outage banner.
 *
 * Polls /api/health/storage every 60s. When healthy=false, renders a thin
 * yellow strip at the top of every authenticated page so users know in
 * advance that uploads will fail. Auto-clears the moment storage recovers.
 *
 * Built after the 2026-05-23 21+ hour Emergent Object Storage outage where
 * users had no way to know what was happening until they tried to upload
 * and got the iter90 fail-fast modal. This is the proactive version — they
 * see the banner the moment they log in, before they invest time setting
 * up a match.
 */

const POLL_MS = 60 * 1000;

const StorageOutageBanner = () => {
  const [healthy, setHealthy] = useState(true);
  const [reason, setReason] = useState('');
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const r = await axios.get(`${API}/health/storage`, { timeout: 15000 });
        if (cancelled) return;
        const ok = r.data?.healthy !== false;
        setHealthy(ok);
        setReason(r.data?.reason || '');
        // If storage came BACK up, undismiss so the user sees the green flash
        // (well — actually we just clear the banner). If still down and the
        // user has dismissed, respect their choice for this session.
        if (ok) setDismissed(false);
      } catch (_) {
        // Probe network blip — assume healthy, don't show a banner just because
        // our own backend was briefly unreachable. Will retry on next tick.
      }
    };

    poll();
    timer = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  if (healthy || dismissed) return null;

  return (
    <div data-testid="storage-outage-banner"
      className="bg-[#F59E0B]/15 border-b border-[#F59E0B]/40 text-[#F59E0B]">
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-3 text-sm">
        <WarningCircle size={18} weight="bold" className="flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="font-bold tracking-wide uppercase text-[11px] mr-2">Storage degraded</span>
          <span className="text-white/80">
            Emergent Object Storage is currently failing
            {reason ? ` (${reason})` : ''}. Uploads are paused — we'll resume automatically when it recovers. Existing videos and clips load normally.
          </span>
        </div>
        <button data-testid="storage-outage-banner-dismiss"
          onClick={() => setDismissed(true)}
          className="text-[#F59E0B]/60 hover:text-white text-xs px-2 py-1 transition-colors flex-shrink-0">
          Hide
        </button>
      </div>
    </div>
  );
};

export default StorageOutageBanner;
