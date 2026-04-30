import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { EnvelopeSimple, ArrowClockwise, CheckCircle, Warning, Clock, X } from '@phosphor-icons/react';

const STATUS_META = {
  sent: { label: 'Sent', color: '#10B981', Icon: CheckCircle },
  quota_deferred: { label: 'Queued (quota)', color: '#FBBF24', Icon: Clock },
  failed: { label: 'Retrying', color: '#F59E0B', Icon: ArrowClockwise },
  failed_permanent: { label: 'Failed', color: '#EF4444', Icon: X },
};

const StatusChip = ({ status }) => {
  const meta = STATUS_META[status] || { label: status, color: '#A3A3A3', Icon: EnvelopeSimple };
  const Icon = meta.Icon;
  return (
    <span className="inline-flex items-center gap-1 text-[9px] font-bold tracking-[0.2em] uppercase px-2 py-0.5"
      style={{ color: meta.color, backgroundColor: `${meta.color}15`, borderColor: `${meta.color}30`, borderWidth: 1, borderStyle: 'solid' }}>
      <Icon size={10} weight="bold" /> {meta.label}
    </span>
  );
};

const EmailQueueCard = () => {
  const [depth, setDepth] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [retryingId, setRetryingId] = useState(null);
  const [lastResult, setLastResult] = useState(null);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/email-queue`, {
        headers: getAuthHeader(),
        params: { limit: 15 },
      });
      setDepth(res.data.depth);
      setItems(res.data.items || []);
    } catch (err) {
      console.error('Failed to load email queue:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);

  const triggerProcess = async () => {
    setProcessing(true);
    setLastResult(null);
    try {
      const res = await axios.post(`${API}/admin/email-queue/process`, {}, { headers: getAuthHeader() });
      setLastResult(res.data);
      await fetchQueue();
    } catch (err) {
      alert('Queue process failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setProcessing(false);
    }
  };

  const retryOne = async (queueId) => {
    setRetryingId(queueId);
    try {
      await axios.post(`${API}/admin/email-queue/${queueId}/retry`, {}, { headers: getAuthHeader() });
      await fetchQueue();
    } catch (err) {
      alert('Retry failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setRetryingId(null);
    }
  };

  if (loading && !depth) {
    return (
      <div data-testid="email-queue-card" className="bg-[#141414] border border-white/10 p-5 mb-6">
        <p className="text-xs text-[#666]">Loading email queue…</p>
      </div>
    );
  }

  if (!depth) return null;

  const urgent = (depth.quota_deferred || 0) + (depth.failed || 0);

  return (
    <div data-testid="email-queue-card"
      className={`bg-[#141414] border p-5 mb-6 ${urgent > 0 ? 'border-[#FBBF24]/30' : 'border-white/10'}`}>
      <div className="flex items-center justify-between mb-4 gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <EnvelopeSimple size={20} className={urgent > 0 ? 'text-[#FBBF24]' : 'text-[#A3A3A3]'} />
          <h3 className="text-sm font-bold tracking-[0.2em] uppercase text-white truncate">Email Queue</h3>
          {urgent > 0 && (
            <span className="text-[9px] font-bold tracking-[0.2em] uppercase text-[#FBBF24] bg-[#FBBF24]/15 border border-[#FBBF24]/30 px-2 py-0.5">
              {urgent} pending
            </span>
          )}
        </div>
        <button data-testid="process-queue-btn" onClick={triggerProcess} disabled={processing}
          className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider uppercase px-3 py-1.5 bg-[#007AFF]/15 text-[#007AFF] hover:bg-[#007AFF]/25 disabled:opacity-50 transition-colors border border-[#007AFF]/30">
          <ArrowClockwise size={12} weight="bold" className={processing ? 'animate-spin' : ''} />
          {processing ? 'Processing…' : 'Retry All Now'}
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3 mb-4">
        {[
          { key: 'sent', label: 'Sent' },
          { key: 'quota_deferred', label: 'Quota Deferred' },
          { key: 'failed', label: 'Retrying' },
          { key: 'failed_permanent', label: 'Failed' },
        ].map(({ key, label }) => {
          const meta = STATUS_META[key] || {};
          return (
            <div key={key} data-testid={`queue-stat-${key}`}
              className="bg-[#0A0A0A] border border-white/5 p-3">
              <div className="text-[9px] font-bold tracking-[0.2em] uppercase mb-1" style={{ color: meta.color || '#A3A3A3' }}>
                {label}
              </div>
              <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>
                {depth[key] || 0}
              </div>
            </div>
          );
        })}
      </div>

      {lastResult && (
        <div className="mb-3 text-xs text-[#A3A3A3] bg-[#0A0A0A] border border-white/5 px-3 py-2">
          Last retry: processed <span className="text-white font-bold">{lastResult.processed}</span>
          {' · '}sent <span className="text-[#10B981] font-bold">{lastResult.sent}</span>
          {' · '}failed <span className="text-[#EF4444] font-bold">{lastResult.failed}</span>
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-xs text-[#666] text-center py-6">No emails queued.</p>
      ) : (
        <div className="space-y-1">
          <div className="text-[9px] font-bold tracking-[0.2em] uppercase text-[#666] px-2 mb-1">
            Recent ({items.length})
          </div>
          {items.map((item) => {
            const canRetry = ['quota_deferred', 'failed'].includes(item.status);
            return (
              <div key={item.id} data-testid={`queue-item-${item.id}`}
                className="flex items-center gap-3 bg-[#0A0A0A] border border-white/5 px-3 py-2 text-xs">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-white font-medium truncate">{item.to_email}</span>
                    <StatusChip status={item.status} />
                    <span className="text-[9px] text-[#666] tracking-wider uppercase">{item.kind}</span>
                  </div>
                  <div className="text-[10px] text-[#666] mt-0.5 truncate">
                    {item.subject}
                    {item.attempts > 1 && <span className="ml-2">· {item.attempts} attempts</span>}
                    {item.last_error && <span className="ml-2 text-[#EF4444] truncate">· {item.last_error.slice(0, 80)}</span>}
                  </div>
                </div>
                {canRetry && (
                  <button data-testid={`retry-${item.id}-btn`} onClick={() => retryOne(item.id)}
                    disabled={retryingId === item.id}
                    className="text-[10px] font-bold tracking-wider uppercase px-2 py-1 bg-[#FBBF24]/15 text-[#FBBF24] hover:bg-[#FBBF24]/25 disabled:opacity-50 border border-[#FBBF24]/30 transition-colors">
                    {retryingId === item.id ? '…' : 'Retry'}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default EmailQueueCard;
