import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, ArrowsClockwise, Bell, ChartBar } from '@phosphor-icons/react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { API, getAuthHeader } from '../App';

/**
 * Admin dashboard for the video-processing pipeline.
 *
 * Renders the iter64 /api/admin/processing-events/stats endpoint as a small
 * set of stat cards + bar charts, plus a recent-failures table and a manual
 * "Run alert check" button that fires the iter64 follow-up Resend alert.
 *
 * This is a thin glass layer over the existing JSON endpoints — no analysis
 * logic lives client-side. If the schema changes server-side, this page
 * gracefully degrades (missing fields render as "—").
 */
const StatCard = ({ label, value, hint, accent = '#7DD3FC' }) => (
  <div data-testid={`stat-card-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`}
    className="bg-[#141414] border border-white/10 p-5">
    <p className="text-[10px] tracking-[0.25em] uppercase text-[#A3A3A3] mb-2">{label}</p>
    <p className="text-3xl font-bold" style={{ fontFamily: 'Space Grotesk', color: accent }}>
      {value ?? '—'}
    </p>
    {hint && <p className="text-xs text-[#666] mt-1">{hint}</p>}
  </div>
);

const Section = ({ title, children, right }) => (
  <section className="mt-6 bg-[#141414] border border-white/10 p-5">
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-sm font-bold tracking-[0.2em] uppercase text-[#E5E5E5]">{title}</h2>
      {right}
    </div>
    {children}
  </section>
);

const FAILURE_MODE_COLOR = {
  oom: '#EF4444',
  timeout: '#FBBF24',
  moov_missing: '#F97316',
  invalid_data: '#A855F7',
  no_space: '#10B981',
  unknown: '#888888',
};
const EVENT_TYPE_COLOR = {
  tier_attempt: '#7DD3FC',
  tier_succeeded: '#10B981',
  tier_failed: '#EF4444',
  final_success: '#22C55E',
  final_failure: '#B91C1C',
};

const AdminProcessingEvents = () => {
  const navigate = useNavigate();
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [topFailed, setTopFailed] = useState(null);
  const [topFailedHours, setTopFailedHours] = useState(24);
  const [loading, setLoading] = useState(true);
  const [alertResult, setAlertResult] = useState(null);
  const [alertBusy, setAlertBusy] = useState(false);

  const fetchAll = useCallback(async (selectedDays, hoursForTop) => {
    setLoading(true);
    try {
      const [s, r, tf] = await Promise.all([
        axios.get(`${API}/admin/processing-events/stats?days=${selectedDays}`, { headers: getAuthHeader() }),
        axios.get(`${API}/admin/processing-events/recent?limit=25`, { headers: getAuthHeader() }),
        axios.get(`${API}/admin/processing-events/top-failed?hours=${hoursForTop}&limit=5`, { headers: getAuthHeader() }),
      ]);
      setStats(s.data);
      setRecent(r.data || []);
      setTopFailed(tf.data);
    } catch (err) {
      if (err.response?.status === 403) navigate('/dashboard');
      console.error('Failed to load processing-events:', err);
    } finally { setLoading(false); }
  }, [navigate]);

  useEffect(() => { fetchAll(days, topFailedHours); }, [days, topFailedHours, fetchAll]);

  const handleAlertCheck = async () => {
    setAlertBusy(true);
    setAlertResult(null);
    try {
      const r = await axios.post(`${API}/admin/processing-alerts/check`, {}, { headers: getAuthHeader() });
      setAlertResult(r.data);
    } catch (err) {
      setAlertResult({ action: 'error', error: err.response?.data?.detail || err.message });
    } finally { setAlertBusy(false); }
  };

  const failureModeRows = stats?.by_failure_mode
    ? Object.entries(stats.by_failure_mode).map(([mode, count]) => ({ name: mode, count, fill: FAILURE_MODE_COLOR[mode] || '#888' }))
    : [];

  const tierRows = stats?.by_tier
    ? Object.entries(stats.by_tier).map(([k, v]) => ({ name: k.length > 30 ? k.slice(0, 30) + '…' : k, count: v }))
    : [];

  const eventTypeRows = stats?.by_event_type
    ? Object.entries(stats.by_event_type).map(([t, c]) => ({ name: t, count: c, fill: EVENT_TYPE_COLOR[t] || '#888' }))
    : [];

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A]/95 backdrop-blur-sm border-b border-white/5 px-6 py-3">
        <div className="max-w-[1400px] mx-auto flex items-center gap-4">
          <button data-testid="back-to-dashboard" onClick={() => navigate('/dashboard')}
            className="p-2 hover:bg-white/5 transition-colors" aria-label="Back">
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-lg font-semibold flex items-center gap-2" style={{ fontFamily: 'Space Grotesk' }}>
            <ChartBar size={20} weight="bold" className="text-[#7DD3FC]" />
            Processing Pipeline Health
          </h1>
          <div className="ml-auto flex items-center gap-2">
            <select data-testid="day-range-select" value={days} onChange={(e) => setDays(Number(e.target.value))}
              className="bg-[#141414] border border-white/10 text-white text-xs px-3 py-1.5">
              <option value={1}>Last 24h</option>
              <option value={7}>Last 7d</option>
              <option value={30}>Last 30d</option>
            </select>
            <button data-testid="refresh-btn" onClick={() => fetchAll(days, topFailedHours)}
              className="p-2 border border-white/10 hover:bg-white/5 transition-colors" aria-label="Refresh">
              <ArrowsClockwise size={14} />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto px-6 py-6">
        {loading && !stats && (
          <p data-testid="loading" className="text-[#A3A3A3] text-sm">Loading pipeline stats…</p>
        )}

        {stats && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <StatCard label="Success rate"
                value={stats.summary.final_success_rate_pct != null ? `${stats.summary.final_success_rate_pct}%` : '—'}
                hint={`${stats.summary.final_success} succeeded · ${stats.summary.final_failure} failed`}
                accent="#22C55E" />
              <StatCard label="Retry save rate"
                value={stats.summary.retry_save_rate_pct != null ? `${stats.summary.retry_save_rate_pct}%` : '—'}
                hint={`${stats.summary.tier1_recoveries} saved by retry tier`}
                accent="#7DD3FC" />
              <StatCard label="OOMs at tier 0"
                value={stats.summary.tier0_oom_count}
                hint="Justifies pod memory bump if rising"
                accent="#EF4444" />
              <StatCard label="Unique videos"
                value={stats.summary.unique_videos}
                hint={`${stats.total_events} events total`}
                accent="#E5E5E5" />
            </div>

            <Section
              title="Top largest failed videos"
              right={
                <div className="flex items-center gap-2">
                  <select data-testid="top-failed-hours-select" value={topFailedHours}
                    onChange={(e) => setTopFailedHours(Number(e.target.value))}
                    className="bg-[#141414] border border-white/10 text-white text-[11px] px-2 py-1">
                    <option value={24}>Today (24h)</option>
                    <option value={72}>Last 3d</option>
                    <option value={168}>Last 7d</option>
                  </select>
                  <span className="text-[10px] text-[#666]">
                    {topFailed?.count ?? 0} shown
                  </span>
                </div>
              }>
              {!topFailed || topFailed.count === 0 ? (
                <p className="text-xs text-[#A3A3A3]" data-testid="no-top-failed-msg">
                  No final failures in this window. 🎉
                </p>
              ) : (
                <div className="overflow-x-auto -mx-2" data-testid="top-failed-table">
                  <table className="min-w-full text-xs">
                    <thead className="text-[#666] text-[10px] tracking-[0.2em] uppercase">
                      <tr>
                        <th className="text-right p-2 w-16">Size</th>
                        <th className="text-left p-2">Filename</th>
                        <th className="text-left p-2">Failure</th>
                        <th className="text-left p-2">Tier reached</th>
                        <th className="text-left p-2">Coach</th>
                        <th className="text-left p-2">Match</th>
                        <th className="text-left p-2">Failed at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topFailed.videos.map((v) => (
                        <tr key={v.video_id}
                          data-testid={`top-failed-row-${v.video_id}`}
                          className="border-t border-white/5 hover:bg-white/[0.02]">
                          <td className="p-2 text-right font-bold" style={{ fontFamily: 'Space Grotesk' }}>
                            {v.size_gb != null ? `${v.size_gb} GB` : '—'}
                          </td>
                          <td className="p-2 text-[#E5E5E5] truncate max-w-[200px]" title={v.filename}>
                            {v.filename}
                          </td>
                          <td className="p-2" style={{ color: FAILURE_MODE_COLOR[v.failure_mode] || '#888' }}>
                            {v.failure_mode}
                          </td>
                          <td className="p-2 text-[#A3A3A3]">
                            {v.tier_label || (v.tier_idx != null ? `tier ${v.tier_idx}` : '—')}
                          </td>
                          <td className="p-2">
                            {v.coach_email ? (
                              <a href={`mailto:${v.coach_email}?subject=Your video upload failed to process`}
                                data-testid={`top-failed-mailto-${v.video_id}`}
                                className="text-[#7DD3FC] hover:underline">
                                {v.coach_name || v.coach_email}
                              </a>
                            ) : (
                              <span className="text-[#666]">—</span>
                            )}
                          </td>
                          <td className="p-2">
                            {v.match_id ? (
                              <button onClick={() => navigate(`/match/${v.match_id}`)}
                                data-testid={`top-failed-open-match-${v.video_id}`}
                                className="text-[#7DD3FC] hover:underline text-left">
                                {v.match_label || 'Open match'}
                              </button>
                            ) : (
                              <span className="text-[#666]">—</span>
                            )}
                          </td>
                          <td className="p-2 text-[#A3A3A3] whitespace-nowrap">
                            {v.failed_at ? new Date(v.failed_at).toLocaleString() : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-[10px] text-[#666] mt-3 px-2">
                    Sorted by source size DESC. Biggest failures point at OOM ceiling or upload-limit UX gaps.
                  </p>
                </div>
              )}
            </Section>

            <Section
              title="Failure modes"
              right={<span className="text-[10px] text-[#666]">last {days}d</span>}>
              {failureModeRows.length === 0 ? (
                <p className="text-xs text-[#A3A3A3]" data-testid="no-failures-msg">No failures recorded in this window. 🎉</p>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={failureModeRows}>
                    <XAxis dataKey="name" tick={{ fill: '#A3A3A3', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#A3A3A3', fontSize: 11 }} allowDecimals={false} />
                    <Tooltip cursor={{ fill: '#FFFFFF08' }} contentStyle={{ background: '#141414', border: '1px solid #2A2A2A', color: '#fff' }} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {failureModeRows.map((row, i) => <Cell key={i} fill={row.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Section>

            <Section title="Attempts by tier">
              {tierRows.length === 0 ? (
                <p className="text-xs text-[#A3A3A3]">No tier attempts recorded.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={tierRows} layout="vertical">
                    <XAxis type="number" tick={{ fill: '#A3A3A3', fontSize: 11 }} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" width={220} tick={{ fill: '#A3A3A3', fontSize: 11 }} />
                    <Tooltip cursor={{ fill: '#FFFFFF08' }} contentStyle={{ background: '#141414', border: '1px solid #2A2A2A', color: '#fff' }} />
                    <Bar dataKey="count" fill="#7DD3FC" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Section>

            <Section title="Event types">
              {eventTypeRows.length === 0 ? (
                <p className="text-xs text-[#A3A3A3]">No events recorded.</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={eventTypeRows}>
                    <XAxis dataKey="name" tick={{ fill: '#A3A3A3', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#A3A3A3', fontSize: 11 }} allowDecimals={false} />
                    <Tooltip cursor={{ fill: '#FFFFFF08' }} contentStyle={{ background: '#141414', border: '1px solid #2A2A2A', color: '#fff' }} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {eventTypeRows.map((row, i) => <Cell key={i} fill={row.fill} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Section>

            <Section
              title="Pipeline alert check"
              right={
                <button data-testid="run-alert-check-btn" onClick={handleAlertCheck} disabled={alertBusy}
                  className="flex items-center gap-2 px-3 py-1.5 bg-[#EF4444]/10 border border-[#EF4444]/30 hover:bg-[#EF4444]/20 text-[#EF4444] text-xs font-bold tracking-wider uppercase transition-colors disabled:opacity-40">
                  <Bell size={12} weight="bold" />
                  {alertBusy ? 'Checking…' : 'Run check now'}
                </button>
              }>
              <p className="text-xs text-[#A3A3A3]">
                Fires the same hourly check that runs automatically. Sends a Resend email only if
                last-hour failure rate exceeds the configured threshold AND we haven't alerted recently
                (de-dup window). Safe to click — won't spam your inbox.
              </p>
              {alertResult && (
                <pre data-testid="alert-result" className="mt-3 bg-[#0A0A0A] border border-white/10 p-3 text-[11px] text-[#A3A3A3] overflow-x-auto rounded">
                  {JSON.stringify(alertResult, null, 2)}
                </pre>
              )}
            </Section>

            <Section title="Recent events">
              {recent.length === 0 ? (
                <p className="text-xs text-[#A3A3A3]">No recent events.</p>
              ) : (
                <div className="overflow-x-auto -mx-2">
                  <table className="min-w-full text-xs">
                    <thead className="text-[#666] text-[10px] tracking-[0.2em] uppercase">
                      <tr>
                        <th className="text-left p-2">Time</th>
                        <th className="text-left p-2">Event</th>
                        <th className="text-left p-2">Tier</th>
                        <th className="text-left p-2">Failure mode</th>
                        <th className="text-right p-2">Source GB</th>
                        <th className="text-right p-2">Duration s</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recent.map((ev) => (
                        <tr key={ev.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                          <td className="p-2 text-[#A3A3A3] whitespace-nowrap">{new Date(ev.created_at).toLocaleString()}</td>
                          <td className="p-2"><span style={{ color: EVENT_TYPE_COLOR[ev.event_type] || '#fff' }}>{ev.event_type}</span></td>
                          <td className="p-2 text-[#A3A3A3]">{ev.tier_label || `tier ${ev.tier_idx ?? '—'}`}</td>
                          <td className="p-2" style={{ color: FAILURE_MODE_COLOR[ev.failure_mode] || '#888' }}>{ev.failure_mode || '—'}</td>
                          <td className="p-2 text-right text-[#A3A3A3]">{ev.source_size_gb ?? '—'}</td>
                          <td className="p-2 text-right text-[#A3A3A3]">{ev.duration_seconds ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          </>
        )}
      </main>
    </div>
  );
};

export default AdminProcessingEvents;
