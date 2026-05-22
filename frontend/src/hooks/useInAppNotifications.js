import { useEffect, useRef } from 'react';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import { showLocalNotification } from '../utils/push';
import { toast } from 'sonner';

/**
 * iter86 — In-app cross-device notifications.
 *
 * Polls /api/me/notifications/recent every 30s and fires local notifications
 * for anything this device hasn't seen yet. Complements the Web Push pipeline
 * (services/push_notifications.py) which only reaches devices that subscribed
 * AND granted permission — this layer catches everyone who's actively in the
 * app on Device B when processing finishes on Device A.
 *
 * "Seen" state is tracked per-device in localStorage so a coach with laptop +
 * phone simultaneously open WANTS both to ping (the whole point), but a
 * single device doesn't re-show the same notification on every poll.
 */

const POLL_MS = 30 * 1000;
const SEEN_PREFIX = 'iter86_seen_notif_ids_';

const _getSeenSet = (userId) => {
  try {
    const raw = localStorage.getItem(SEEN_PREFIX + userId);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw));
  } catch {
    return new Set();
  }
};

const _saveSeenSet = (userId, set) => {
  try {
    // Cap the persisted set at 200 ids — protects against unbounded growth on
    // a long-running tab. Order doesn't matter for membership checks.
    const arr = Array.from(set).slice(-200);
    localStorage.setItem(SEEN_PREFIX + userId, JSON.stringify(arr));
  } catch {
    /* localStorage full or disabled — silently degrade */
  }
};

const useInAppNotifications = (isAuthenticated) => {
  const lastPollRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    const user = getCurrentUser();
    if (!user?.id) return undefined;

    let cancelled = false;

    const poll = async () => {
      try {
        const since = lastPollRef.current || new Date(Date.now() - 5 * 60 * 1000).toISOString();
        const res = await axios.get(`${API}/me/notifications/recent`, {
          headers: getAuthHeader(),
          params: { since },
        });
        if (cancelled) return;
        lastPollRef.current = new Date().toISOString();
        const notifs = res.data?.notifications || [];
        if (notifs.length === 0) return;

        const seen = _getSeenSet(user.id);
        const fresh = notifs.filter((n) => n.id && !seen.has(n.id));
        for (const n of fresh) {
          // Browser notification (no-op if permission not granted)
          showLocalNotification(n.title, {
            body: n.body,
            url: n.deep_link || '/',
            tag: `notif-${n.id}`,
          });
          // In-app toast — works regardless of permission
          toast.success(n.title, {
            description: n.body,
            duration: 8000,
            action: n.deep_link ? {
              label: 'Open',
              onClick: () => { window.location.href = n.deep_link; },
            } : undefined,
          });
          seen.add(n.id);
        }
        if (fresh.length > 0) _saveSeenSet(user.id, seen);
      } catch (err) {
        // Silent — network blip / 401 logout / etc. Next tick retries.
        if (err.response?.status === 401) {
          // Stop polling; user signed out.
          cancelled = true;
          if (timerRef.current) clearInterval(timerRef.current);
        }
      }
    };

    // Immediate first poll, then every POLL_MS
    poll();
    timerRef.current = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isAuthenticated]);
};

export default useInAppNotifications;
