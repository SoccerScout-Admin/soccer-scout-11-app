import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Envelope, CheckCircle, BellRinging, BellSlash } from '@phosphor-icons/react';
import { API, getAuthHeader } from '../../App';
import {
  isPushSupported, isIosButNotInstalled, requestPushPermission,
  subscribeToPush, unsubscribeFromPush, sendTestPush, getSubscriptionCount,
} from '../../utils/push';

/**
 * Email Settings card — coaches can subscribe/unsubscribe to the weekly Coach Pulse digest
 * + send themselves a test email to preview the format.
 */
const CoachPulseCard = () => {
  const [isActive, setIsActive] = useState(false);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [testStatus, setTestStatus] = useState(null);
  const [pushActive, setPushActive] = useState(false);
  const [pushSupported] = useState(() => isPushSupported());
  const [needsInstall] = useState(() => isIosButNotInstalled());
  const [pushBusy, setPushBusy] = useState(false);

  const fetchSubscription = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/coach-pulse/subscription`, { headers: getAuthHeader() });
      setIsActive(!!res.data.is_active);
      setEmail(res.data.email || '');
    } catch {
      // ignore — endpoint might be unavailable
    }
  }, []);

  useEffect(() => { fetchSubscription(); }, [fetchSubscription]);

  // Check initial push subscription state
  useEffect(() => {
    (async () => {
      if (!pushSupported) return;
      const count = await getSubscriptionCount();
      setPushActive(count > 0 && Notification.permission === 'granted');
    })();
  }, [pushSupported]);

  const togglePush = async () => {
    setPushBusy(true);
    setTestStatus(null);
    try {
      if (pushActive) {
        await unsubscribeFromPush();
        setPushActive(false);
      } else {
        const perm = await requestPushPermission();
        if (!perm.granted) {
          setTestStatus({ kind: 'err', text: perm.reason || 'Permission denied' });
          return;
        }
        await subscribeToPush();
        setPushActive(true);
        // Fire a confirmation ping
        try {
          await sendTestPush();
          setTestStatus({ kind: 'ok', text: 'Push enabled — check your notifications' });
        } catch { /* noop */ }
      }
    } catch (err) {
      setTestStatus({ kind: 'err', text: err.response?.data?.detail || err.message || 'Push setup failed' });
    } finally {
      setPushBusy(false);
      setTimeout(() => setTestStatus(null), 8000);
    }
  };

  const toggle = async () => {
    setBusy(true);
    try {
      const path = isActive ? 'unsubscribe' : 'subscribe';
      await axios.post(`${API}/coach-pulse/${path}`, {}, { headers: getAuthHeader() });
      setIsActive(!isActive);
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    setBusy(true);
    setTestStatus(null);
    try {
      const res = await axios.post(`${API}/coach-pulse/send-test`, {}, { headers: getAuthHeader() });
      setTestStatus({ kind: 'ok', text: `Sent to ${res.data.to}` });
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to send';
      setTestStatus({ kind: 'err', text: detail });
    } finally {
      setBusy(false);
      setTimeout(() => setTestStatus(null), 8000);
    }
  };

  const openPreview = async () => {
    setBusy(true);
    try {
      const res = await axios.get(`${API}/coach-pulse/preview`, {
        headers: getAuthHeader(),
        responseType: 'text',
      });
      const blob = new Blob([res.data], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      // Revoke after the new tab has loaded it
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (err) {
      setTestStatus({ kind: 'err', text: 'Preview failed' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="coach-pulse-card"
      className="w-full mb-6 bg-gradient-to-r from-[#0E1B2E] via-[#0A0A0A] to-[#0A0A0A] border border-[#0EA5E9]/30 px-5 py-4">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 bg-[#0EA5E9]/15 border border-[#0EA5E9]/30 flex items-center justify-center flex-shrink-0">
          <Envelope size={24} weight="bold" className="text-[#0EA5E9]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#0EA5E9] mb-1">Coach Pulse</div>
          <div className="text-base font-bold text-white truncate">Weekly digest of network themes + your stats</div>
          <div className="text-xs text-[#A3A3A3] mt-0.5 truncate">
            {isActive ? `Subscribed → ${email}` : 'Get a Monday-morning summary of what coaches across the platform are talking about'}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button data-testid="coach-pulse-preview-btn"
            onClick={openPreview} disabled={busy}
            className="hidden sm:inline-flex items-center text-xs text-[#A3A3A3] hover:text-white border border-white/10 px-3 py-1.5 transition-colors font-bold uppercase tracking-wider disabled:opacity-50">
            Preview
          </button>
          <button data-testid="coach-pulse-test-btn"
            onClick={sendTest} disabled={busy}
            className="hidden sm:inline-flex items-center text-xs text-[#0EA5E9] hover:text-white hover:bg-[#0EA5E9]/15 border border-[#0EA5E9]/30 px-3 py-1.5 transition-colors font-bold uppercase tracking-wider disabled:opacity-50">
            {busy ? '...' : 'Send Test'}
          </button>
          <button data-testid="coach-pulse-toggle-btn"
            onClick={toggle} disabled={busy}
            className={`inline-flex items-center gap-1 text-xs font-bold uppercase tracking-wider px-3 py-1.5 border transition-colors ${
              isActive
                ? 'bg-[#0EA5E9] text-white border-[#0EA5E9] hover:bg-[#0284C7]'
                : 'text-[#0EA5E9] border-[#0EA5E9]/40 hover:bg-[#0EA5E9]/15'
            } disabled:opacity-50`}>
            {isActive && <CheckCircle size={12} weight="bold" />}
            {isActive ? 'Subscribed' : 'Subscribe'}
          </button>
        </div>
      </div>

      {/* Push toggle row — only shown on browsers that support Web Push */}
      {(pushSupported || needsInstall) && (
        <div data-testid="push-toggle-row" className="mt-3 pt-3 border-t border-white/5 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            {pushActive ? <BellRinging size={16} weight="bold" className="text-[#10B981] flex-shrink-0" /> : <BellSlash size={16} className="text-[#666] flex-shrink-0" />}
            <div className="min-w-0">
              <div className="text-[11px] font-bold uppercase tracking-wider text-white">Push notifications</div>
              <div className="text-[10px] text-[#A3A3A3] truncate">
                {needsInstall
                  ? 'iOS: install the app to your home screen first'
                  : pushActive
                  ? 'Alerts for AI analysis done · shared-clip views'
                  : "Get a tap when AI finishes or someone opens your shared clip"}
              </div>
            </div>
          </div>
          {pushSupported && !needsInstall && (
            <button data-testid="push-toggle-btn"
              onClick={togglePush} disabled={pushBusy}
              className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 border transition-colors flex-shrink-0 ${
                pushActive
                  ? 'bg-[#10B981] text-white border-[#10B981] hover:bg-[#059669]'
                  : 'text-[#10B981] border-[#10B981]/40 hover:bg-[#10B981]/15'
              } disabled:opacity-50`}>
              {pushBusy ? '...' : pushActive ? 'Enabled' : 'Enable'}
            </button>
          )}
        </div>
      )}
      {testStatus && (
        <div data-testid="coach-pulse-status"
          className={`mt-3 text-[11px] px-3 py-2 ${
            testStatus.kind === 'ok'
              ? 'bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/30'
              : 'bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/30'
          }`}>
          {testStatus.text}
        </div>
      )}
    </div>
  );
};

export default CoachPulseCard;
