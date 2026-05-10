import { useEffect, useState, useCallback, useMemo } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import {
  FilmReel, Sparkle, DownloadSimple, ShareNetwork, Copy, Check, Trash,
  ArrowClockwise, WhatsappLogo, TwitterLogo, X,
} from '@phosphor-icons/react';

const formatDuration = (seconds) => {
  if (!seconds || seconds <= 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`;
};

const formatRelative = (iso) => {
  if (!iso) return '';
  const then = new Date(iso);
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return then.toLocaleDateString();
};

const ReelCard = ({ reel, onShareToggled, onDeleted, onRetried }) => {
  const [shareBusy, setShareBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const isReady = reel.status === 'ready';
  const isFailed = reel.status === 'failed';
  const isInFlight = reel.status === 'pending' || reel.status === 'processing';
  const progressPct = Math.round((reel.progress || 0) * 100);
  const ogUrl = reel.share_token ? `${window.location.origin}/api/og/highlight-reel/${reel.share_token}` : '';

  const toggleShare = useCallback(async () => {
    setShareBusy(true);
    try {
      const res = await axios.post(`${API}/highlight-reels/${reel.id}/share`, {}, { headers: getAuthHeader() });
      onShareToggled(reel.id, res.data.share_token);
    } catch (err) {
      alert('Failed to update share link: ' + (err.response?.data?.detail || err.message));
    } finally {
      setShareBusy(false);
    }
  }, [reel.id, onShareToggled]);

  const copyShareLink = useCallback(async () => {
    if (!ogUrl) return;
    try {
      await navigator.clipboard.writeText(ogUrl);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = ogUrl;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [ogUrl]);

  const handleDownload = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/highlight-reels/${reel.id}/video`, {
        headers: getAuthHeader(), responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'video/mp4' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `highlight-reel-${reel.id.slice(0, 8)}.mp4`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert('Download failed: ' + (err.response?.data?.detail || err.message));
    }
  }, [reel.id]);

  const handleDelete = useCallback(async () => {
    if (!window.confirm('Delete this highlight reel? The mp4 file will be removed.')) return;
    try {
      await axios.delete(`${API}/highlight-reels/${reel.id}`, { headers: getAuthHeader() });
      onDeleted(reel.id);
    } catch (err) {
      alert('Delete failed: ' + (err.response?.data?.detail || err.message));
    }
  }, [reel.id, onDeleted]);

  const handleRetry = useCallback(async () => {
    try {
      await axios.post(`${API}/highlight-reels/${reel.id}/retry`, {}, { headers: getAuthHeader() });
      onRetried();
    } catch (err) {
      alert('Retry failed: ' + (err.response?.data?.detail || err.message));
    }
  }, [reel.id, onRetried]);

  return (
    <div data-testid={`reel-card-${reel.id}`}
      className={`bg-[#0A0A0A] border ${isReady ? 'border-[#10B981]/30' : isFailed ? 'border-[#EF4444]/30' : 'border-white/10'} p-4 sm:p-5`}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1.5">
            <FilmReel size={16} weight="fill" className="text-[#007AFF]" />
            <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A3A3A3]">
              {isReady ? 'Ready' : isFailed ? 'Failed' : 'Building'}
            </span>
            <span className="text-[10px] text-[#666]">· {formatRelative(reel.created_at)}</span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold text-white tabular-nums" style={{ fontFamily: 'Bebas Neue' }}>
              {formatDuration(reel.duration_seconds)}
            </span>
            <span className="text-xs text-[#A3A3A3]">
              {reel.total_clips || 0} {reel.total_clips === 1 ? 'clip' : 'clips'}
            </span>
          </div>
        </div>
        <button data-testid={`delete-reel-${reel.id}`} onClick={handleDelete}
          className="p-1.5 text-[#666] hover:text-[#EF4444] transition-colors" aria-label="Delete reel">
          <Trash size={16} />
        </button>
      </div>

      {isInFlight && (
        <div className="mb-3" data-testid={`reel-progress-${reel.id}`}>
          <div className="flex items-center gap-2 text-[10px] tracking-wider uppercase font-bold text-[#FBBF24] mb-1.5">
            <div className="w-2 h-2 bg-[#FBBF24] rounded-full animate-pulse" />
            {reel.status === 'pending' ? 'Queued' : `Processing… ${progressPct}%`}
          </div>
          <div className="h-1 bg-[#1F1F1F] overflow-hidden">
            <div className="h-full bg-gradient-to-r from-[#007AFF] to-[#10B981] transition-all duration-500"
              style={{ width: `${Math.max(5, progressPct)}%` }} />
          </div>
        </div>
      )}

      {isFailed && (
        <div className="mb-3 bg-[#EF4444]/10 border border-[#EF4444]/30 px-3 py-2 text-xs text-[#EF4444]">
          <strong className="block tracking-wider uppercase font-bold mb-0.5">Build Failed</strong>
          {reel.error || 'Something went wrong during reel generation.'}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {isReady && (
          <>
            <button data-testid={`download-reel-${reel.id}`} onClick={handleDownload}
              className="flex items-center gap-1.5 bg-[#007AFF] hover:bg-[#005bb5] text-white px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase transition-colors">
              <DownloadSimple size={12} weight="bold" /> Download
            </button>
            <button data-testid={`share-reel-${reel.id}`} onClick={toggleShare} disabled={shareBusy}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase transition-colors ${
                reel.share_token
                  ? 'bg-[#10B981] text-black hover:bg-[#0e9d6c]'
                  : 'border border-white/10 text-white hover:bg-[#1F1F1F]'
              }`}>
              <ShareNetwork size={12} weight="bold" /> {reel.share_token ? 'Sharing On' : 'Share'}
            </button>
            {reel.share_token && (
              <>
                <button data-testid={`copy-reel-link-${reel.id}`} onClick={copyShareLink}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase transition-colors ${
                    copied ? 'bg-[#10B981] text-black' : 'border border-white/10 text-white hover:bg-[#1F1F1F]'
                  }`}>
                  {copied ? <><Check size={12} weight="bold" /> Copied</> : <><Copy size={12} /> Copy Link</>}
                </button>
                <a href={`https://wa.me/?text=${encodeURIComponent(`Match highlights: ${ogUrl}`)}`} target="_blank" rel="noopener noreferrer"
                  data-testid={`share-wa-${reel.id}`}
                  className="flex items-center gap-1.5 border border-white/10 hover:border-[#25D366]/40 px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase text-[#A3A3A3] hover:text-white transition-colors">
                  <WhatsappLogo size={12} weight="bold" /> WhatsApp
                </a>
                <a href={`https://twitter.com/intent/tweet?text=${encodeURIComponent('Match highlights')}&url=${encodeURIComponent(ogUrl)}`} target="_blank" rel="noopener noreferrer"
                  data-testid={`share-tw-${reel.id}`}
                  className="flex items-center gap-1.5 border border-white/10 hover:border-[#1DA1F2]/40 px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase text-[#A3A3A3] hover:text-white transition-colors">
                  <TwitterLogo size={12} weight="bold" /> Twitter
                </a>
              </>
            )}
          </>
        )}
        {isFailed && (
          <button data-testid={`retry-reel-${reel.id}`} onClick={handleRetry}
            className="flex items-center gap-1.5 bg-[#FBBF24] hover:bg-[#D9A11F] text-black px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase transition-colors">
            <ArrowClockwise size={12} weight="bold" /> Retry
          </button>
        )}
      </div>
    </div>
  );
};

const HighlightReelsPanel = ({ matchId }) => {
  const [reels, setReels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(false);

  const fetchReels = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/matches/${matchId}/highlight-reels`, { headers: getAuthHeader() });
      setReels(res.data || []);
    } catch (err) {
      // 404 means the match itself doesn't exist — leave reels empty silently.
      if (err.response?.status !== 404) {
        console.warn('Failed to fetch reels:', err);
      }
    } finally {
      setLoading(false);
    }
  }, [matchId]);

  useEffect(() => {
    fetchReels();
  }, [fetchReels]);

  // Poll while any reel is in flight
  const hasInFlight = useMemo(
    () => reels.some((r) => r.status === 'pending' || r.status === 'processing'),
    [reels],
  );
  useEffect(() => {
    if (!hasInFlight) return undefined;
    const id = setInterval(fetchReels, 5000);
    return () => clearInterval(id);
  }, [hasInFlight, fetchReels]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      await axios.post(`${API}/matches/${matchId}/highlight-reel`, {}, { headers: getAuthHeader() });
      await fetchReels();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start reel generation.');
    } finally {
      setGenerating(false);
    }
  }, [matchId, fetchReels]);

  const handleShareToggled = useCallback((reelId, newToken) => {
    setReels((prev) => prev.map((r) => (r.id === reelId ? { ...r, share_token: newToken } : r)));
  }, []);
  const handleDeleted = useCallback((reelId) => {
    setReels((prev) => prev.filter((r) => r.id !== reelId));
  }, []);

  return (
    <div className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-[#007AFF]/30 p-5 sm:p-6 mb-6"
      data-testid="highlight-reels-panel">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <Sparkle size={18} weight="fill" className="text-[#007AFF]" />
            <h3 className="text-xl sm:text-2xl font-bold tracking-wider uppercase text-white" style={{ fontFamily: 'Bebas Neue' }}>
              Auto-Highlight Reels
            </h3>
          </div>
          <p className="text-xs text-[#A3A3A3] leading-relaxed">
            AI picks your top clips (goals first), stitches them with branded title cards,
            and outputs a 60-90s reel ready to share to socials.
          </p>
        </div>
        <button
          data-testid="toggle-reels-collapse"
          onClick={() => setCollapsed(!collapsed)}
          className="text-[#A3A3A3] hover:text-white p-1"
          aria-label="Toggle panel">
          <X size={18} style={{ transform: collapsed ? 'rotate(45deg)' : 'none', transition: 'transform 0.2s' }} />
        </button>
      </div>

      {!collapsed && (
        <>
          <button
            data-testid="generate-reel-btn"
            onClick={handleGenerate}
            disabled={generating || hasInFlight}
            className="w-full sm:w-auto flex items-center justify-center gap-2 bg-gradient-to-r from-[#007AFF] to-[#10B981] text-white px-5 py-3 text-sm font-bold tracking-wider uppercase hover:opacity-90 disabled:opacity-50 transition-opacity mb-4">
            {generating ? (
              <>
                <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Starting…
              </>
            ) : hasInFlight ? (
              <>
                <Sparkle size={16} weight="fill" />
                Reel In Progress…
              </>
            ) : (
              <>
                <Sparkle size={16} weight="fill" />
                Generate Highlight Reel
              </>
            )}
          </button>

          {error && (
            <div data-testid="reel-error"
              className="mb-4 bg-[#EF4444]/10 border border-[#EF4444]/30 text-[#EF4444] px-4 py-3 text-xs">
              {error}
            </div>
          )}

          {loading ? (
            <p className="text-[10px] tracking-wider uppercase text-[#666]">Loading…</p>
          ) : reels.length === 0 ? (
            <div data-testid="no-reels-empty" className="text-center py-6 border border-dashed border-white/10">
              <FilmReel size={32} className="text-[#333] mx-auto mb-2" />
              <p className="text-xs text-[#A3A3A3]">
                No reels yet. Generate one once your match has clips.
              </p>
            </div>
          ) : (
            <div className="space-y-3" data-testid="reels-list">
              {reels.map((r) => (
                <ReelCard
                  key={r.id}
                  reel={r}
                  onShareToggled={handleShareToggled}
                  onDeleted={handleDeleted}
                  onRetried={fetchReels}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default HighlightReelsPanel;
