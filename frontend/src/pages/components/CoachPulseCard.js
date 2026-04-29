import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Envelope, CheckCircle } from '@phosphor-icons/react';
import { API, getAuthHeader } from '../../App';

/**
 * Email Settings card — coaches can subscribe/unsubscribe to the weekly Coach Pulse digest
 * + send themselves a test email to preview the format.
 */
const CoachPulseCard = () => {
  const [isActive, setIsActive] = useState(false);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [testStatus, setTestStatus] = useState(null);

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
