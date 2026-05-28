import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  ArrowLeft, Database, Copy, CheckCircle, Trash, ChartLine, Warning,
} from '@phosphor-icons/react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { API, getAuthHeader } from '../App';

/**
 * iter94 — Storage Cleanup admin page.
 *
 * Three jobs:
 *   1. Show the iter93 orphan-chunk inventory (totals + breakdown by bucket)
 *      so the user can SEE how their object-storage quota got eaten.
 *   2. One-click "Copy email to support" that drafts the exact escalation
 *      message with their user_id + bucket totals baked in.
 *   3. "Mark as ready for purge" button — persists the orphan paths to
 *      the orphan_chunks collection so when Emergent ships a DELETE API
 *      we have a sweep-ready ledger.
 *   4. Sparkline of the weekly storage-growth audits so the user can tell
 *      whether orphan accumulation is still climbing post-fix.
 */

const BUCKET_LABELS = {
  dismissed_sessions: 'Dismissed paused uploads',
  abandoned_uploads: 'Abandoned in-progress uploads (>6h stale)',
  completed_uploads_without_video: 'Completed uploads with no video record',
  failed_videos: 'Failed videos (recoverable)',
  stuck_videos: 'Stuck videos (processing >2h, OOM-killed)',
  deleted_videos: 'Deleted videos',
  lost_chunks: 'Lost chunks (already gone)',
};

const BUCKET_COLOR = {
  dismissed_sessions: '#FBBF24',
  abandoned_uploads: '#A855F7',
  completed_uploads_without_video: '#0EA5E9',
  failed_videos: '#F97316',
  stuck_videos: '#EC4899',
  deleted_videos: '#DC2626',
  lost_chunks: '#888888',
};

const StatCard = ({ label, value, sub, accent }) => (
  <div
    data-testid={`stat-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`}
    className="bg-[#141414] border border-white/10 p-5"
  >
    <p className="text-[10px] tracking-[0.25em] uppercase text-[#A3A3A3] mb-2">{label}</p>
    <p className="text-3xl font-bold" style={{ fontFamily: 'Space Grotesk', color: accent || '#7DD3FC' }}>
      {value}
    </p>
    {sub && <p className="text-xs text-[#666] mt-1">{sub}</p>}
  </div>
);

const AdminStorageCleanup = () => {
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [audits, setAudits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [markBusy, setMarkBusy] = useState(false);
  const [markResult, setMarkResult] = useState(null);
  const [copied, setCopied] = useState(false);
  const [digestOptOut, setDigestOptOut] = useState(false);
  const [digestBusy, setDigestBusy] = useState(false);
  const [digestResult, setDigestResult] = useState(null);
  // iter105 — pod memory chip + escalation
  const [memory, setMemory] = useState(null);
  const [podEmailCopied, setPodEmailCopied] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [r, a, pref, mem] = await Promise.all([
        axios.get(`${API}/admin/storage-cleanup/report`, { headers: getAuthHeader() }),
        axios.get(`${API}/admin/storage-cleanup/audit-history?days=90`, { headers: getAuthHeader() }),
        axios.get(`${API}/me/preferences/storage-digest`, { headers: getAuthHeader() }),
        axios.get(`${API}/health/memory`).catch(() => ({ data: null })),
      ]);
      setReport(r.data);
      setAudits(a.data.audits || []);
      setDigestOptOut(!!pref.data.opt_out);
      setMemory(mem.data);
    } catch (err) {
      console.error('Failed to load storage cleanup data', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleMarkOrphans = async () => {
    setMarkBusy(true);
    setMarkResult(null);
    try {
      const r = await axios.post(
        `${API}/admin/storage-cleanup/mark-orphans`,
        {},
        { headers: getAuthHeader() },
      );
      setMarkResult(r.data);
    } catch (err) {
      setMarkResult({ error: err.response?.data?.detail || err.message });
    } finally {
      setMarkBusy(false);
    }
  };

  const handleToggleDigest = async () => {
    const next = !digestOptOut;
    setDigestOptOut(next);
    try {
      await axios.post(
        `${API}/me/preferences/storage-digest`,
        { opt_out: next },
        { headers: getAuthHeader() },
      );
    } catch (err) {
      setDigestOptOut(!next);  // rollback
      alert('Could not save preference: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleSendDigestNow = async () => {
    setDigestBusy(true);
    setDigestResult(null);
    try {
      const r = await axios.post(
        `${API}/admin/storage-cleanup/send-digest-now`,
        {},
        { headers: getAuthHeader() },
      );
      setDigestResult(r.data);
    } catch (err) {
      setDigestResult({ status: 'error', reason: err.response?.data?.detail || err.message });
    } finally {
      setDigestBusy(false);
    }
  };

  // iter105 — One-click "Email Support" for pod-bump escalation
  const handleCopyPodBumpEmail = async () => {
    if (!memory) return;
    const subject = `Pod memory bump request — cgroup still at ${memory.cgroup_limit_gb} GB`;
    const body = `Hello Emergent Support team,

Following up on a previous ticket: I was told my Soccer Scout production pod would be bumped from 4 GB to 20 GB so video processing for full-match game film can complete without OOM cycling.

The bump has not landed. Here is the live probe from production (https://soccerscout11.com/api/health/memory):

  cgroup_limit_gb:  ${memory.cgroup_limit_gb}
  cgroup_path:      ${memory.cgroup_path}
  process_rss_gb:   ${memory.process_rss_gb}
  host_total_gb:    ${memory.host_total_gb}
  verdict:          ${memory.verdict}

Concrete impact: 1+ GB compressed game-film videos (1080p30 source, HandBrake-compressed to the recommended preset) trigger the iter97 pod-OOM-cycle detector within seconds because ffmpeg + Python + Motor + FastAPI together exceed the 4 GB cgroup limit during segment encoding. Users see the iter97 yellow "falling back to lighter encoding" banner but processing never completes meaningfully because the safe tier (480p / 12fps) is the only one that fits in 4 GB.

The host has ${memory.host_total_gb} GB of memory available, so this is purely a cgroup-limit adjustment on your side. Could you please bump the cgroup limit on the Soccer Scout production pod (soccerscout11.com) to 20 GB as previously committed?

Thanks,
`;
    const mailto = `mailto:support@emergent.sh?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    try {
      await navigator.clipboard.writeText(`To: support@emergent.sh\nSubject: ${subject}\n\n${body}`);
      setPodEmailCopied(true);
      setTimeout(() => setPodEmailCopied(false), 3000);
    } catch { /* clipboard unavailable; mailto still works */ }
    window.location.href = mailto;
  };


  const handleCopySupportEmail = async () => {
    if (!report) return;
    const s = report.summary;
    const bucketLines = Object.entries(s.by_bucket || {})
      .map(([k, v]) => `  • ${BUCKET_LABELS[k] || k}: ${v} chunks`)
      .join('\n');

    const body = `Hello Emergent Support team,

My Soccer Scout app account (user_id: ${report.user_id}) has hit its object-storage capacity limit.

I've audited my app data and confirmed that ${s.total_orphan_chunks} chunks (~${s.total_estimated_gb} GB) are safe to delete because they belong to either:

${bucketLines}

The full JSON manifest (with every chunk path) was generated at ${report.generated_at} via GET /api/admin/storage-cleanup/report on my account. I can email it as an attachment if you reply with how to forward it.

Could you please run a one-time server-side purge of these paths so I can resume uploading? The app's public storage API does not expose DELETE (Allow: PUT, GET, HEAD), so I have no way to reclaim this myself.

Thank you,
`;
    const subject = 'Manual purge requested — orphan chunks from failed/dismissed uploads';
    const mailto = `mailto:support@emergent.sh?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

    // Copy the body to clipboard too, so the user can paste into any web mail
    try {
      await navigator.clipboard.writeText(`To: support@emergent.sh\nSubject: ${subject}\n\n${body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch {
      /* clipboard may not be available — mailto: still works */
    }
    window.location.href = mailto;
  };

  const summary = report?.summary || { total_orphan_chunks: 0, total_estimated_gb: 0, by_bucket: {} };
  const bucketRows = Object.entries(summary.by_bucket || {}).map(([k, v]) => ({
    key: k,
    label: BUCKET_LABELS[k] || k,
    count: v,
    color: BUCKET_COLOR[k] || '#888',
  }));
  const chartRows = audits.map((a) => ({
    date: a.recorded_at?.slice(0, 10) || '—',
    chunks: a.total_orphan_chunks || 0,
    gb: a.total_estimated_gb || 0,
  }));

  return (
    <div data-testid="storage-cleanup-page" className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A]/95 backdrop-blur-sm border-b border-white/5 px-6 py-3">
        <div className="max-w-[1400px] mx-auto flex items-center gap-4">
          <button
            data-testid="back-to-dashboard"
            onClick={() => navigate('/dashboard')}
            className="p-2 hover:bg-white/5 transition-colors"
            aria-label="Back"
          >
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-lg font-semibold flex items-center gap-2" style={{ fontFamily: 'Space Grotesk' }}>
            <Database size={20} weight="bold" className="text-[#FBBF24]" />
            Storage Cleanup
          </h1>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto px-6 py-8">
        {/* Why this page exists */}
        <section className="bg-[#1A1206] border-l-4 border-[#FBBF24] p-5 mb-6">
          <div className="flex items-start gap-3">
            <Warning size={22} weight="bold" className="text-[#FBBF24] mt-0.5 flex-shrink-0" />
            <div className="text-sm text-[#E5E5E5] leading-relaxed">
              <p className="font-semibold mb-2 text-[#FBBF24]">
                Why is my storage full when no upload ever finished?
              </p>
              <p>
                Every chunk you upload is written to Emergent Object Storage <strong>immediately</strong>.
                When an upload fails, gets dismissed from the resume banner, or the pod restarts mid-finalize,
                those chunks <strong>stay in storage forever</strong> — there's no DELETE endpoint exposed
                to the app (Emergent's API allows only PUT, GET, HEAD). Across many upload attempts, this
                builds up to dozens of GB of orphans that count against your quota even though they're
                unreachable through the app.
              </p>
              <p className="mt-2">
                <strong>How to reclaim:</strong> click <em>Copy email to support</em> below.
                It opens your mail client with a pre-filled request to <code className="text-[#7DD3FC]">support@emergent.sh</code>{' '}
                including your user_id and the exact orphan totals — they can run a one-time server-side purge.
              </p>
            </div>
          </div>
        </section>

        {loading ? (
          <p className="text-sm text-[#A3A3A3]">Loading storage report…</p>
        ) : (
          <>
            {/* Top-line stats */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              <StatCard
                label="Orphan chunks"
                value={summary.total_orphan_chunks?.toLocaleString() || '0'}
                sub="Across all buckets below"
                accent="#FBBF24"
              />
              <StatCard
                label="Wasted storage"
                value={`~${summary.total_estimated_gb || 0} GB`}
                sub="Reclaimable by support"
                accent="#F97316"
              />
              <StatCard
                label="Buckets affected"
                value={bucketRows.filter((b) => b.count > 0).length}
                sub="See breakdown below"
                accent="#7DD3FC"
              />
            </div>

            {/* Action buttons */}
            <section className="bg-[#141414] border border-white/10 p-5 mb-6">
              <h2 className="text-sm font-bold tracking-[0.2em] uppercase text-[#E5E5E5] mb-4">
                Take Action
              </h2>
              <div className="flex flex-col sm:flex-row gap-3">
                <button
                  data-testid="copy-support-email-btn"
                  onClick={handleCopySupportEmail}
                  disabled={summary.total_orphan_chunks === 0}
                  className="flex items-center justify-center gap-2 bg-[#FBBF24] text-black font-semibold px-5 py-3 hover:bg-[#F59E0B] transition-colors disabled:opacity-30 disabled:cursor-not-allowed text-sm"
                >
                  {copied ? <CheckCircle size={18} weight="bold" /> : <Copy size={18} weight="bold" />}
                  {copied ? 'Copied to clipboard + mail client opened' : 'Copy email to support'}
                </button>
                <button
                  data-testid="mark-orphans-btn"
                  onClick={handleMarkOrphans}
                  disabled={markBusy || summary.total_orphan_chunks === 0}
                  className="flex items-center justify-center gap-2 bg-[#141414] border border-white/20 text-white font-semibold px-5 py-3 hover:bg-white/5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed text-sm"
                >
                  <Trash size={18} weight="bold" />
                  {markBusy ? 'Marking…' : 'Mark as ready for purge'}
                </button>
              </div>
              <p className="text-xs text-[#666] mt-3 leading-relaxed">
                <strong className="text-[#A3A3A3]">Mark as ready for purge:</strong>{' '}
                records every orphan path to a local ledger so when Emergent ships a DELETE API,
                we can sweep them all instantly. Safe to re-click — it's idempotent.
              </p>
              {markResult && !markResult.error && (
                <p data-testid="mark-orphans-result" className="text-xs text-[#10B981] mt-3">
                  ✓ Marked {markResult.newly_marked} new paths
                  ({markResult.refreshed} already tracked). Total awaiting purge: {markResult.total_marked_now}.
                </p>
              )}
              {markResult?.error && (
                <p className="text-xs text-[#EF4444] mt-3">Error: {markResult.error}</p>
              )}
            </section>

            {/* iter105 — Pod memory chip + escalation */}
            {memory && (
              <section data-testid="pod-memory-section" className="bg-[#141414] border border-white/10 p-5 mb-6">
                <div className="flex items-center justify-between gap-4 flex-wrap">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{
                        backgroundColor:
                          memory.verdict === '20gb-class-pod-confirmed' ? '#10B981'
                          : memory.verdict === '8gb-class-pod' ? '#FBBF24'
                          : '#EF4444',
                      }}
                    />
                    <div>
                      <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#E5E5E5]">
                        Encoder Pod Memory
                      </p>
                      <p className="text-[11px] text-[#A3A3A3] mt-0.5">
                        cgroup: <span data-testid="pod-memory-cgroup-gb" className="text-white font-semibold tabular-nums">{memory.cgroup_limit_gb} GB</span>
                        {' · '}using <span className="tabular-nums">{memory.process_rss_gb} GB</span>
                        {' · '}host has <span className="tabular-nums">{memory.host_total_gb} GB</span>
                      </p>
                    </div>
                  </div>
                  {memory.verdict === '4gb-or-smaller-pod-needs-support-bump' && (
                    <button
                      data-testid="pod-bump-email-btn"
                      onClick={handleCopyPodBumpEmail}
                      className="flex items-center gap-2 bg-[#EF4444] text-white font-semibold px-4 py-2 hover:bg-[#DC2626] transition-colors text-xs"
                    >
                      {podEmailCopied ? <CheckCircle size={14} weight="bold" /> : <Copy size={14} weight="bold" />}
                      {podEmailCopied ? 'Copied + mail client opened' : 'Request pod bump from support'}
                    </button>
                  )}
                </div>
                {memory.verdict === '4gb-or-smaller-pod-needs-support-bump' && (
                  <p className="text-[11px] text-[#EF4444] mt-3 leading-relaxed">
                    <strong>Your pod is memory-constrained.</strong> 1+ GB game-film videos can't process the full iter101 quality tier (720p + scdet) because total encoder memory exceeds the 4 GB cgroup limit. The iter103 fallback to 480p sampling works but produces lower-quality goal/jersey detection. Click the button above to email Support — the request body is pre-filled with the live probe evidence.
                  </p>
                )}
                {memory.verdict === '8gb-class-pod' && (
                  <p className="text-[11px] text-[#FBBF24] mt-3 leading-relaxed">
                    <strong>Mid-tier pod.</strong> Files up to ~1.5 GB should complete at full iter101 quality. Anything larger falls back to the iter103 safe tier (480p).
                  </p>
                )}
                {memory.verdict === '20gb-class-pod-confirmed' && (
                  <p className="text-[11px] text-[#10B981] mt-3 leading-relaxed">
                    <strong>Full-quality tier confirmed.</strong> All file sizes will run the full iter101 pipeline (720p + scene-cut sampling).
                  </p>
                )}
              </section>
            )}

            {/* iter96 — Weekly digest email preferences */}
            <section data-testid="digest-preferences-section" className="bg-[#141414] border border-white/10 p-5 mb-6">
              <h2 className="text-sm font-bold tracking-[0.2em] uppercase text-[#E5E5E5] mb-4">
                Weekly storage digest
              </h2>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div className="flex-1">
                  <p className="text-sm text-[#E5E5E5] mb-1">
                    Email alert when orphan storage grows ≥ 1 GB in a week
                  </p>
                  <p className="text-xs text-[#666] leading-relaxed">
                    Turns silent quota loss into an inbox signal. Only fires on meaningful growth — no weekly spam.
                  </p>
                </div>
                <label className="flex items-center gap-3 cursor-pointer select-none">
                  <span className={`text-xs uppercase tracking-wider ${digestOptOut ? 'text-[#666]' : 'text-[#10B981]'}`}>
                    {digestOptOut ? 'OFF' : 'ON'}
                  </span>
                  <button
                    data-testid="toggle-digest-btn"
                    onClick={handleToggleDigest}
                    role="switch"
                    aria-checked={!digestOptOut}
                    className={`relative w-12 h-6 transition-colors ${digestOptOut ? 'bg-[#333]' : 'bg-[#10B981]'}`}
                  >
                    <span
                      className={`absolute top-0.5 ${digestOptOut ? 'left-0.5' : 'left-6'} w-5 h-5 bg-white transition-all`}
                    />
                  </button>
                </label>
              </div>
              <div className="mt-4 pt-4 border-t border-white/5">
                <button
                  data-testid="send-test-digest-btn"
                  onClick={handleSendDigestNow}
                  disabled={digestBusy || digestOptOut}
                  className="text-xs tracking-wider uppercase border border-[#7DD3FC] text-[#7DD3FC] hover:bg-[#7DD3FC]/10 px-4 py-2 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  {digestBusy ? 'Sending…' : 'Send me a test digest now'}
                </button>
                {digestResult && (
                  <p
                    data-testid="digest-send-result"
                    className={`text-xs mt-3 ${digestResult.status === 'sent' || digestResult.status === 'quota_deferred' ? 'text-[#10B981]' : 'text-[#A3A3A3]'}`}
                  >
                    {digestResult.status === 'sent' && '✓ Digest sent — check your inbox.'}
                    {digestResult.status === 'quota_deferred' && '⏳ Queued — will retry within the hour.'}
                    {digestResult.status === 'skipped' && `Skipped: ${digestResult.reason}`}
                    {digestResult.status === 'error' && `Error: ${digestResult.reason}`}
                    {digestResult.status === 'failed' && `Failed: ${digestResult.reason || 'unknown'}`}
                  </p>
                )}
              </div>
            </section>

            {/* Bucket breakdown */}
            <section className="bg-[#141414] border border-white/10 p-5 mb-6">
              <h2 className="text-sm font-bold tracking-[0.2em] uppercase text-[#E5E5E5] mb-4">
                Breakdown by source
              </h2>
              {summary.total_orphan_chunks === 0 ? (
                <p className="text-sm text-[#10B981]">
                  ✓ No orphan chunks detected. Your storage is clean.
                </p>
              ) : (
                <div className="space-y-2">
                  {bucketRows.map((b) => (
                    <div
                      key={b.key}
                      data-testid={`bucket-row-${b.key}`}
                      className="flex items-center justify-between p-3 bg-[#0A0A0A] border border-white/5"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: b.color }}
                        />
                        <span className="text-sm text-[#E5E5E5]">{b.label}</span>
                      </div>
                      <span
                        className="text-sm font-bold tabular-nums"
                        style={{ fontFamily: 'Space Grotesk', color: b.color }}
                      >
                        {b.count.toLocaleString()} chunks
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Weekly trend chart */}
            <section className="bg-[#141414] border border-white/10 p-5">
              <div className="flex items-center gap-2 mb-4">
                <ChartLine size={18} weight="bold" className="text-[#7DD3FC]" />
                <h2 className="text-sm font-bold tracking-[0.2em] uppercase text-[#E5E5E5]">
                  Weekly storage-growth trend (90 days)
                </h2>
              </div>
              {chartRows.length === 0 ? (
                <p className="text-xs text-[#666]">
                  No audit snapshots yet — the weekly background job runs every Monday.
                  Come back next week to see the trend, or hit{' '}
                  <em>Mark as ready for purge</em> now to seed your first datapoint.
                </p>
              ) : (
                <div data-testid="audit-history-chart" style={{ width: '100%', height: 240 }}>
                  <ResponsiveContainer>
                    <LineChart data={chartRows}>
                      <CartesianGrid stroke="#1A1A1A" />
                      <XAxis dataKey="date" stroke="#666" style={{ fontSize: 11 }} />
                      <YAxis stroke="#666" style={{ fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#0A0A0A', border: '1px solid #333', fontSize: 12,
                        }}
                        labelStyle={{ color: '#A3A3A3' }}
                      />
                      <Line
                        type="monotone"
                        dataKey="chunks"
                        stroke="#FBBF24"
                        strokeWidth={2}
                        dot={{ fill: '#FBBF24', r: 3 }}
                        name="Orphan chunks"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
};

export default AdminStorageCleanup;
