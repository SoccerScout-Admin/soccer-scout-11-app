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
  const [recipientEmail, setRecipientEmail] = useState('');
  const [recipientName, setRecipientName] = useState('');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);  // {lens_link, tracked_url, email_status}

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
  };

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

          {!result && (
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
