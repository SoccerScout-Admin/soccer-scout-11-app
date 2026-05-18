/**
 * RecruiterOutreachModal
 * ----------------------
 * Coach-facing modal that emails a college recruiter a tracked, filtered
 * lens link. Companion to TeamRoster's "Share this view" copy-link flow —
 * the difference is this one records who clicked.
 *
 * Required props:
 *   teamId — UUID of the team to filter on
 *   teamName — display label for header context
 *   filters — { birth_year?, class_of?, position? } pulled from current
 *             TeamRoster filter state. Already stripped to truthy values.
 *
 * The component renders nothing if `open` is false.
 */
import { useState } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { X, EnvelopeSimple, Funnel, CheckCircle, Warning, PaperPlaneTilt } from '@phosphor-icons/react';

const RecruiterOutreachModal = ({ open, teamId, teamName, filters, onClose, onSent }) => {
  const [mode, setMode] = useState('single'); // 'single' | 'blast'
  const [recipientEmail, setRecipientEmail] = useState('');
  const [recipientName, setRecipientName] = useState('');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);  // single send: {lens_link, tracked_url, email_status}
  const [blastCsv, setBlastCsv] = useState('');
  const [blastResult, setBlastResult] = useState(null);  // bulk send: { summary, results }

  if (!open) return null;

  const filterChips = [];
  if (filters?.class_of) filterChips.push(`Class of ${filters.class_of}`);
  if (filters?.birth_year) filterChips.push(`Born ${filters.birth_year}`);
  if (filters?.position) filterChips.push(filters.position);

  const reset = () => {
    setRecipientEmail('');
    setRecipientName('');
    setMessage('');
    setError('');
    setResult(null);
    setBlastCsv('');
    setBlastResult(null);
  };

  // Parse the CSV/TSV/newline-separated input into {email, name?} rows.
  // Skip blank lines, comment lines (#), and header rows (case-insensitive).
  // Multi-format: handles `email` / `email,name` / `name <email>` / `email\tname`.
  const parseBlastCsv = (raw) => {
    const out = [];
    const seen = new Set();
    const lines = raw.split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      if (/^email\b/i.test(trimmed)) continue;  // header row
      // RFC 5322-ish "Name <email@x.com>"
      const angleMatch = trimmed.match(/^(.*?)\s*<\s*([^>]+@[^>]+)\s*>\s*$/);
      let email, name;
      if (angleMatch) {
        name = angleMatch[1].trim() || null;
        email = angleMatch[2].trim();
      } else {
        // Try comma/tab split
        const parts = trimmed.split(/[,\t]/).map((p) => p.trim()).filter(Boolean);
        // Whichever part contains @ is the email
        const emailIdx = parts.findIndex((p) => p.includes('@'));
        if (emailIdx < 0) continue;  // no email on this row, skip
        email = parts[emailIdx];
        const nameParts = parts.filter((_, i) => i !== emailIdx);
        name = nameParts.length ? nameParts.join(' ') : null;
      }
      const key = email.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ email, name });
    }
    return out;
  };

  const parsedRecipients = mode === 'blast' ? parseBlastCsv(blastCsv) : [];

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!recipientEmail.trim()) return;
    setSending(true);
    setError('');
    try {
      const res = await axios.post(`${API}/lens-links`, {
        team_id: teamId,
        filters: filters || {},
        recipient_email: recipientEmail.trim(),
        recipient_name: recipientName.trim() || null,
        message: message.trim() || null,
      }, { headers: getAuthHeader() });
      setResult(res.data);
      onSent?.(res.data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not send. Please try again.');
    } finally {
      setSending(false);
    }
  };

  const handleBlastSubmit = async (e) => {
    e.preventDefault();
    if (parsedRecipients.length === 0) return;
    setSending(true);
    setError('');
    try {
      const res = await axios.post(`${API}/lens-links/blast`, {
        team_id: teamId,
        filters: filters || {},
        recipients: parsedRecipients,
        message: message.trim() || null,
      }, { headers: getAuthHeader() });
      setBlastResult(res.data);
      onSent?.(res.data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Blast failed — try again.');
    } finally {
      setSending(false);
    }
  };

  return (
    <div data-testid="recruiter-outreach-modal-overlay" onClick={handleClose}
      className="fixed inset-0 z-[100] bg-black/70 overflow-y-auto p-4 sm:flex sm:items-center sm:justify-center">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-white/10 max-w-xl w-full mx-auto my-4 sm:my-0">
        <div className="flex items-start justify-between px-6 py-4 border-b border-white/10">
          <div>
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#10B981] mb-1">Recruiter Outreach</div>
            <h3 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>
              {result ? 'Email Sent' : 'Email a Recruiter'}
            </h3>
          </div>
          <button data-testid="close-outreach-modal" onClick={handleClose}
            className="p-1 text-[#666] hover:text-white">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-5">
          {/* Filter preview chips */}
          {filterChips.length > 0 && (
            <div className="bg-[#0A0A0A] border border-white/10 px-4 py-3 flex flex-wrap items-center gap-2">
              <Funnel size={14} weight="fill" className="text-[#10B981]" />
              <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mr-1">Sending</span>
              {filterChips.map((c, i) => (
                <span key={i} className="px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase bg-[#10B981]/15 border border-[#10B981]/30 text-[#10B981]">
                  {c}
                </span>
              ))}
              <span className="text-xs text-[#666] ml-1">from {teamName}</span>
            </div>
          )}

          {/* Mode toggle: single recipient vs CSV blast */}
          {!result && !blastResult && (
            <div className="flex border border-white/10" data-testid="outreach-mode-toggle">
              <button data-testid="mode-single-btn" type="button"
                onClick={() => { setMode('single'); setError(''); }}
                className={`flex-1 py-2 text-[10px] font-bold tracking-[0.2em] uppercase transition-colors ${
                  mode === 'single' ? 'bg-[#10B981] text-white' : 'text-[#A3A3A3] hover:bg-[#1F1F1F]'
                }`}>
                One recipient
              </button>
              <button data-testid="mode-blast-btn" type="button"
                onClick={() => { setMode('blast'); setError(''); }}
                className={`flex-1 py-2 text-[10px] font-bold tracking-[0.2em] uppercase transition-colors ${
                  mode === 'blast' ? 'bg-[#10B981] text-white' : 'text-[#A3A3A3] hover:bg-[#1F1F1F]'
                }`}>
                Mass blast (CSV)
              </button>
            </div>
          )}

          {!result && !blastResult && mode === 'single' && (
            <form data-testid="outreach-form" onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1.5">
                  Recipient email *
                </label>
                <input data-testid="recipient-email-input" type="email" required
                  placeholder="coach.smith@school.edu"
                  value={recipientEmail}
                  onChange={(e) => setRecipientEmail(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none" />
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1.5">
                  Recipient name (optional)
                </label>
                <input data-testid="recipient-name-input" type="text"
                  placeholder="Coach Smith"
                  value={recipientName}
                  onChange={(e) => setRecipientName(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none" />
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1.5">
                  Personal note (optional)
                </label>
                <textarea data-testid="message-input" rows="3"
                  placeholder="A short message to add context..."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none resize-none" />
              </div>
              {error && (
                <div data-testid="outreach-error"
                  className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm flex items-start gap-2">
                  <Warning size={18} weight="fill" className="flex-shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}
              <button data-testid="send-outreach-btn" type="submit" disabled={sending || !recipientEmail.trim()}
                className="w-full flex items-center justify-center gap-2 bg-[#10B981] hover:bg-[#0EA975] disabled:opacity-50 disabled:cursor-not-allowed text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                <PaperPlaneTilt size={14} weight="fill" />
                {sending ? 'Sending...' : 'Send Email'}
              </button>
              <p className="text-[10px] text-[#666] leading-relaxed text-center">
                We track when the recipient opens the link, so you'll see if it landed.
                Your contact info is never shared with us.
              </p>
            </form>
          )}

          {!result && !blastResult && mode === 'blast' && (
            <form data-testid="blast-form" onSubmit={handleBlastSubmit} className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1.5">
                  Recipients (one per line)
                </label>
                <textarea data-testid="blast-csv-input" rows="6"
                  placeholder={'coach.smith@school.edu\ncoach.jones@uni.edu, Coach Jones\nCoach Brown <brown@college.edu>'}
                  value={blastCsv}
                  onChange={(e) => setBlastCsv(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none resize-none font-mono text-sm" />
                <p className="text-[10px] text-[#666] mt-1.5">
                  One per line. Accepts <code>email</code>, <code>email, name</code>, or <code>Name &lt;email&gt;</code>. Headers, blank lines, and <code>#</code> comments are ignored.
                </p>
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1.5">
                  Shared note (optional)
                </label>
                <textarea data-testid="blast-message-input" rows="2"
                  placeholder="One personal note sent to every recipient..."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none resize-none" />
              </div>
              {parsedRecipients.length > 0 && (
                <div data-testid="blast-preview" className="bg-[#0A0A0A] border border-white/10 p-3 max-h-32 overflow-y-auto">
                  <div className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1.5">
                    Preview · {parsedRecipients.length} unique recipient{parsedRecipients.length === 1 ? '' : 's'}
                  </div>
                  <ul className="text-xs text-[#CFCFCF] space-y-0.5">
                    {parsedRecipients.slice(0, 8).map((r, i) => (
                      <li key={i} className="font-mono">
                        {r.email}{r.name ? ` — ${r.name}` : ''}
                      </li>
                    ))}
                    {parsedRecipients.length > 8 && (
                      <li className="text-[#666]">+ {parsedRecipients.length - 8} more</li>
                    )}
                  </ul>
                </div>
              )}
              {error && (
                <div data-testid="blast-error"
                  className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm flex items-start gap-2">
                  <Warning size={18} weight="fill" className="flex-shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}
              <button data-testid="send-blast-btn" type="submit" disabled={sending || parsedRecipients.length === 0}
                className="w-full flex items-center justify-center gap-2 bg-[#10B981] hover:bg-[#0EA975] disabled:opacity-50 disabled:cursor-not-allowed text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                <PaperPlaneTilt size={14} weight="fill" />
                {sending ? 'Blasting...' : `Blast ${parsedRecipients.length || 0} recipient${parsedRecipients.length === 1 ? '' : 's'}`}
              </button>
              <p className="text-[10px] text-[#666] leading-relaxed text-center">
                Each recipient gets a unique tracking link. Daily cap of 25 across all your sends — keeps inboxes happy.
              </p>
            </form>
          )}

          {blastResult && (
            <div data-testid="blast-success" className="space-y-3">
              <div className="bg-[#10B981]/10 border border-[#10B981]/30 px-4 py-3">
                <div className="text-sm font-bold text-[#10B981]">
                  Blast complete · {blastResult.summary.sent + blastResult.summary.queued} of {blastResult.summary.total_unique_recipients} delivered
                </div>
                <div className="text-xs text-[#A3A3A3] mt-1">
                  ✓ {blastResult.summary.sent} sent
                  {blastResult.summary.queued > 0 && ` · ⏳ ${blastResult.summary.queued} queued (Resend quota)`}
                  {blastResult.summary.skipped_over_cap > 0 && ` · ⚠ ${blastResult.summary.skipped_over_cap} skipped (daily cap)`}
                  {blastResult.summary.failed > 0 && ` · ✗ ${blastResult.summary.failed} failed`}
                </div>
              </div>
              <div className="bg-[#0A0A0A] border border-white/10 max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[10px] tracking-[0.2em] uppercase text-[#666] border-b border-white/10">
                      <th className="text-left p-2">Recipient</th>
                      <th className="text-left p-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {blastResult.results.map((r, i) => (
                      <tr key={i} className="border-t border-white/5">
                        <td className="p-2 text-[#CFCFCF] truncate max-w-[280px]" title={r.email}>{r.email}{r.name ? ` (${r.name})` : ''}</td>
                        <td className="p-2" style={{
                          color: r.status === 'sent' ? '#22C55E'
                            : r.status === 'quota_deferred' ? '#FBBF24'
                            : r.status === 'skipped_over_cap' ? '#F97316'
                            : '#EF4444',
                        }}>{r.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button data-testid="blast-done-btn" onClick={reset}
                className="w-full flex items-center justify-center gap-2 border border-white/10 hover:bg-[#1F1F1F] text-white py-2.5 font-bold tracking-wider uppercase text-xs transition-colors">
                Send another blast
              </button>
            </div>
          )}

          {result && (
            <div data-testid="outreach-success" className="space-y-4">
              <div className="bg-[#10B981]/10 border border-[#10B981]/30 px-4 py-3 flex items-start gap-3">
                <CheckCircle size={20} weight="fill" className="text-[#10B981] flex-shrink-0 mt-0.5" />
                <div>
                  <div className="text-sm font-bold text-[#10B981]">
                    Sent to {result.lens_link.recipient_email}
                  </div>
                  <div className="text-xs text-[#A3A3A3] mt-0.5">
                    {result.email_status === 'sent'
                      ? 'Delivered via Resend. Track opens in the panel below.'
                      : result.email_status === 'quota_deferred'
                      ? 'Email queued — will retry automatically when quota resets.'
                      : 'Queued for retry.'}
                  </div>
                </div>
              </div>
              <div className="bg-[#0A0A0A] border border-white/10 p-4">
                <div className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Tracked link</div>
                <code className="block text-xs text-[#CFCFCF] font-mono break-all">{result.tracked_url}</code>
              </div>
              <button data-testid="send-another-btn" onClick={reset}
                className="w-full flex items-center justify-center gap-2 border border-white/10 hover:bg-[#1F1F1F] text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                <EnvelopeSimple size={14} weight="bold" /> Send another
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RecruiterOutreachModal;
