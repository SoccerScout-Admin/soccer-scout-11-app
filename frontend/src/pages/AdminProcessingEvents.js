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
  incomplete_upload: '#0EA5E9',  // sky blue — distinct from the "file too big" reds/oranges
  pod_oom_loop: '#DC2626',  // dark red — even worse than single oom (pod killed N×)
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
  const [emailingVideoId, setEmailingVideoId] = useState(null);
  const [emailAudit, setEmailAudit] = useState(null);
  const [emailAuditKind, setEmailAuditKind] = useState('');
  const [emptyRoster, setEmptyRoster] = useState(null);
  const [reminderingMatchId, setReminderingMatchId] = useState(null);

  const fetchAll = useCallback(async (selectedDays, hoursForTop, auditKind) => {
    setLoading(true);
    try {
      const auditUrl = `${API}/admin/email-audit-log?days=${selectedDays}${auditKind ? `&kind=${auditKind}` : ''}`;
      const [s, r, tf, ea, er] = await Promise.all([
        axios.get(`${API}/admin/processing-events/stats?days=${selectedDays}`, { headers: getAuthHeader() }),
        axios.get(`${API}/admin/processing-events/recent?limit=25`, { headers: getAuthHeader() }),
        axios.get(`${API}/admin/processing-events/top-failed?hours=${hoursForTop}&limit=5`, { headers: getAuthHeader() }),
        axios.get(auditUrl, { headers: getAuthHeader() }),
        axios.get(`${API}/admin/empty-roster-matches?days=14&limit=25`, { headers: getAuthHeader() }),
      ]);
      setStats(s.data);
      setRecent(r.data || []);
      setTopFailed(tf.data);
      setEmailAudit(ea.data);
      setEmptyRoster(er.data);
    } catch (err) {
      if (err.response?.status === 403) navigate('/dashboard');
      console.error('Failed to load processing-events:', err);
    } finally { setLoading(false); }
  }, [navigate]);

  useEffect(() => { fetchAll(days, topFailedHours, emailAuditKind); }, [days, topFailedHours, emailAuditKind, fetchAll]);

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

  const handleSendRosterReminder = async (matchId, coachEmail) => {
    if (!coachEmail) {
      alert("This row has no coach email on record — nothing to send to.");
      return;
    }
    const ok = window.confirm(
      `Send a roster-reminder email to ${coachEmail}?\n\nTheir match has an uploaded video but 0 players, so AI tactical attribution can't run. The email points them at the in-product ⚡ Quick Attach pill for a one-click recovery.`
    );
    if (!ok) return;
    setReminderingMatchId(matchId);
    try {
      const r = await axios.post(
        `${API}/admin/empty-roster-matches/send-reminder`,
        { match_id: matchId },
        { headers: getAuthHeader() }
      );
      if (r.data.status === "sent" || r.data.status === "quota_deferred") {
        alert(`Reminder ${r.data.status === "sent" ? "sent" : "queued"} to ${r.data.to_email || coachEmail}.`);
      } else if (r.data.status === "already_sent") {
        alert(`Already sent to ${r.data.to_email} at ${new Date(r.data.sent_at).toLocaleString()}. Skipped.`);
      } else {
        alert(`Skipped: ${r.data.reason || "unknown"}`);
      }
      await fetchAll(days, topFailedHours, emailAuditKind);
    } catch (err) {
      alert("Failed to send: " + (err.response?.data?.detail || err.message));
    } finally {
      setReminderingMatchId(null);
    }
  };

  const handleEmailFix = async (videoId, coachEmail) => {
    if (!coachEmail) {
      alert("This row has no coach email on record — nothing to send to.");
      return;
    }
    const ok = window.confirm(
      `Send compression-fix instructions to ${coachEmail}?\n\nThis will trigger one Resend email with HandBrake settings. It's safe to click — repeat clicks on the same row are de-duped server-side.`
    );
    if (!ok) return;
    setEmailingVideoId(videoId);
    try {
      const r = await axios.post(
        `${API}/admin/processing-events/email-compression-help`,
        { video_id: videoId },
        { headers: getAuthHeader() }
      );
      if (r.data.status === "sent" || r.data.status === "quota_deferred") {
        alert(`Email ${r.data.status === "sent" ? "sent" : "queued"} to ${r.data.to_email || coachEmail}.`);
      } else if (r.data.status === "already_sent") {
        alert(`Already sent to ${r.data.to_email} at ${new Date(r.data.sent_at).toLocaleString()}. Skipped.`);
      } else {
        alert(`Skipped: ${r.data.reason || "unknown"}`);
      }
      // Refresh to surface the new sent_at timestamp
      await fetchAll(days, topFailedHours, emailAuditKind);
    } catch (err) {
      alert("Failed to send: " + (err.response?.data?.detail || err.message));
    } finally {
      setEmailingVideoId(null);
    }
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
            <button data-testid="refresh-btn" onClick={() => fetchAll(days, topFailedHours, emailAuditKind)}
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
                        <th className="text-left p-2">Help</th>
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
                          <td className="p-2">
                            {v.compression_email_sent_at ? (
                              <span data-testid={`compression-email-sent-${v.video_id}`}
                                title={`Sent ${new Date(v.compression_email_sent_at).toLocaleString()}`}
                                className="inline-flex items-center gap-1 text-[10px] text-[#22C55E] font-bold tracking-wider uppercase">
                                ✓ Sent
                              </span>
                            ) : (
                              <button
                                data-testid={`email-fix-btn-${v.video_id}`}
                                onClick={() => handleEmailFix(v.video_id, v.coach_email)}
                                disabled={!v.coach_email || emailingVideoId === v.video_id}
                                title={v.coach_email
                                  ? (v.failure_mode === 'incomplete_upload'
                                      ? "Send the coach 'upload got cut off — re-upload from a stable network' instructions"
                                      : "Send the coach HandBrake compression instructions")
                                  : "No coach email on record"}
                                className="inline-flex items-center gap-1 px-2 py-1 border border-[#FBBF24]/40 bg-[#FBBF24]/10 text-[#FBBF24] hover:bg-[#FBBF24]/20 text-[10px] font-bold tracking-wider uppercase transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                                {emailingVideoId === v.video_id ? 'Sending…' : 'Email fix'}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-[10px] text-[#666] mt-3 px-2">
                    Sorted by source size DESC. Biggest failures point at OOM ceiling or upload-limit UX gaps. "Email fix" sends one Resend email with HandBrake 720p30/CQ28 instructions — de-duped per video.
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

            <Section
              title="Empty-roster matches"
              right={
                <span className="text-[10px] text-[#666]" data-testid="empty-roster-summary">
                  {emptyRoster?.count ?? 0} match{emptyRoster?.count === 1 ? '' : 'es'} need roster · last 14d
                </span>
              }>
              {!emptyRoster || emptyRoster.count === 0 ? (
                <p className="text-xs text-[#A3A3A3]" data-testid="no-empty-roster-msg">
                  No matches with uploaded videos + empty rosters. 🎉
                </p>
              ) : (
                <div className="overflow-x-auto -mx-2" data-testid="empty-roster-table">
                  <table className="min-w-full text-xs">
                    <thead className="text-[#666] text-[10px] tracking-[0.2em] uppercase">
                      <tr>
                        <th className="text-left p-2">Match</th>
                        <th className="text-left p-2">Date</th>
                        <th className="text-left p-2">Coach</th>
                        <th className="text-left p-2">Video uploaded</th>
                        <th className="text-left p-2">Reminder</th>
                      </tr>
                    </thead>
                    <tbody>
                      {emptyRoster.matches.map((m) => (
                        <tr key={m.match_id}
                          data-testid={`empty-roster-row-${m.match_id}`}
                          className="border-t border-white/5 hover:bg-white/[0.02]">
                          <td className="p-2">
                            <button onClick={() => navigate(`/match/${m.match_id}`)}
                              className="text-[#7DD3FC] hover:underline text-left">
                              {m.match_label || 'Open match'}
                            </button>
                          </td>
                          <td className="p-2 text-[#A3A3A3] whitespace-nowrap">{m.match_date || '—'}</td>
                          <td className="p-2">
                            {m.coach_email ? (
                              <a href={`mailto:${m.coach_email}`}
                                className="text-[#7DD3FC] hover:underline">
                                {m.coach_name || m.coach_email}
                              </a>
                            ) : (
                              <span className="text-[#666]">—</span>
                            )}
                          </td>
                          <td className="p-2 text-[#A3A3A3] whitespace-nowrap">
                            {m.video_uploaded_at ? new Date(m.video_uploaded_at).toLocaleString() : '—'}
                          </td>
                          <td className="p-2">
                            {m.reminder_sent_at ? (
                              <span data-testid={`roster-reminder-sent-${m.match_id}`}
                                title={`Sent ${new Date(m.reminder_sent_at).toLocaleString()}`}
                                className="inline-flex items-center gap-1 text-[10px] text-[#22C55E] font-bold tracking-wider uppercase">
                                ✓ Sent
                              </span>
                            ) : (
                              <button
                                data-testid={`roster-reminder-btn-${m.match_id}`}
                                onClick={() => handleSendRosterReminder(m.match_id, m.coach_email)}
                                disabled={!m.coach_email || reminderingMatchId === m.match_id}
                                title={m.coach_email
                                  ? "Email the coach a one-click roster-attach reminder"
                                  : "No coach email on record"}
                                className="inline-flex items-center gap-1 px-2 py-1 border border-[#FBBF24]/40 bg-[#FBBF24]/10 text-[#FBBF24] hover:bg-[#FBBF24]/20 text-[10px] font-bold tracking-wider uppercase transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                                {reminderingMatchId === m.match_id ? 'Sending…' : 'Send reminder'}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-[10px] text-[#666] mt-3 px-2">
                    Matches where the video processed cleanly but the roster is empty — AI tactical attribution produces 0 player-credited
                    events on these. The reminder points the coach at the in-product ⚡ Quick Attach pill for a 2-click fix.
                  </p>
                </div>
              )}
            </Section>

            <Section
              title="Admin email audit"
              right={
                <div className="flex items-center gap-2">
                  <select data-testid="email-audit-kind-select" value={emailAuditKind}
                    onChange={(e) => setEmailAuditKind(e.target.value)}
                    className="bg-[#141414] border border-white/10 text-white text-[11px] px-2 py-1">
                    <option value="">All templates</option>
                    <option value="compression_help">compression_help</option>
                    <option value="incomplete_upload_help">incomplete_upload_help</option>
                    <option value="hot_lead">hot_lead</option>
                    <option value="processing_alert">processing_alert</option>
                  </select>
                  {emailAudit && (
                    <span className="text-[10px] text-[#666]" data-testid="email-audit-summary">
                      {emailAudit.opened}/{emailAudit.sent} opened ({Math.round((emailAudit.open_rate || 0) * 100)}%)
                    </span>
                  )}
                </div>
              }>
              {!emailAudit || emailAudit.total === 0 ? (
                <p className="text-xs text-[#A3A3A3]" data-testid="no-audit-rows-msg">
                  No transactional emails sent in this window.
                </p>
              ) : (
                <div className="overflow-x-auto -mx-2" data-testid="email-audit-table">
                  <table className="min-w-full text-xs">
                    <thead className="text-[#666] text-[10px] tracking-[0.2em] uppercase">
                      <tr>
                        <th className="text-left p-2">Sent</th>
                        <th className="text-left p-2">Template</th>
                        <th className="text-left p-2">Recipient</th>
                        <th className="text-left p-2">Subject</th>
                        <th className="text-left p-2">Status</th>
                        <th className="text-left p-2">Opened</th>
                      </tr>
                    </thead>
                    <tbody>
                      {emailAudit.rows.map((row) => {
                        const opened = !!row.opened_at;
                        return (
                          <tr key={row.id}
                            data-testid={`email-audit-row-${row.id}`}
                            className="border-t border-white/5 hover:bg-white/[0.02]">
                            <td className="p-2 text-[#A3A3A3] whitespace-nowrap">
                              {row.sent_at ? new Date(row.sent_at).toLocaleString()
                                : row.created_at ? new Date(row.created_at).toLocaleString()
                                : '—'}
                            </td>
                            <td className="p-2 text-[#E5E5E5]">{row.kind}</td>
                            <td className="p-2 text-[#7DD3FC] truncate max-w-[200px]" title={row.to_email}>
                              {row.to_email}
                            </td>
                            <td className="p-2 text-[#A3A3A3] truncate max-w-[280px]" title={row.subject}>
                              {row.subject}
                            </td>
                            <td className="p-2" style={{
                              color: row.status === 'sent' ? '#22C55E'
                                : row.status === 'quota_deferred' ? '#FBBF24'
                                : row.status === 'failed' ? '#EF4444' : '#888',
                            }}>{row.status || '—'}</td>
                            <td className="p-2">
                              {opened ? (
                                <span data-testid={`email-audit-opened-${row.id}`}
                                  title={`First opened ${new Date(row.opened_at).toLocaleString()}${row.open_count > 1 ? ` · ${row.open_count} opens total` : ''}`}
                                  className="inline-flex items-center gap-1 text-[#22C55E] font-bold tracking-wider uppercase text-[10px]">
                                  ✓ {row.open_count > 1 ? `${row.open_count}×` : 'Opened'}
                                </span>
                              ) : (
                                <span className="text-[10px] text-[#666]">unopened</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="text-[10px] text-[#666] mt-3 px-2">
                    Open tracking via a 1x1 pixel embedded in each templated email. Gmail/Apple Mail auto-load images;
                    Outlook desktop sometimes blocks them, so "unopened" doesn't always mean unread — but the signal is high enough to
                    compare relative open-rates across template families (see by_kind in the summary above).
                  </p>
                </div>
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
