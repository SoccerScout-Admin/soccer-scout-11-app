import { useState, useEffect } from 'react';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../../App';
import { X, PaperPlaneRight, Warning, Paperclip } from '@phosphor-icons/react';

const ExpressInterestModal = ({ listingId, schoolName, onClose, onSent }) => {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [sharedPlayers, setSharedPlayers] = useState([]);
  const [attachToken, setAttachToken] = useState('');
  const user = getCurrentUser();

  useEffect(() => {
    axios.get(`${API}/players/my-shared`, { headers: getAuthHeader() })
      .then(res => setSharedPlayers(res.data || []))
      .catch(() => setSharedPlayers([]));
  }, []);

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (message.trim().length < 10) {
      setError('Please write at least a couple of sentences (min 10 characters).');
      return;
    }
    setSending(true);
    try {
      const payload = { message: message.trim() };
      if (attachToken) payload.player_dossier_share_token = attachToken;
      const res = await axios.post(
        `${API}/scout-listings/${listingId}/express-interest`,
        payload,
        { headers: getAuthHeader() },
      );
      onSent(res.data);
      onClose();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to send. Please try again.');
    } finally {
      setSending(false);
    }
  };

  return (
    <div data-testid="interest-modal"
      className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center overflow-y-auto"
      onClick={onClose}>
      <div className="bg-[#141414] border border-white/10 max-w-lg w-full mx-4 my-8"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h3 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Express Interest</h3>
            <p className="text-xs text-[#A3A3A3]">Reach out to <span className="text-white">{schoolName}</span></p>
          </div>
          <button data-testid="interest-close-btn" onClick={onClose}
            className="p-2 hover:bg-[#1F1F1F] transition-colors">
            <X size={20} className="text-[#A3A3A3]" />
          </button>
        </div>

        <form onSubmit={onSubmit} className="p-6 space-y-4">
          <p className="text-sm text-[#CFCFCF]">
            Send a personal note. The recruiter receives an email immediately and can reply
            in-app from their inbox. Your message also opens a private thread under <span className="text-[#10B981] font-bold">Messages</span>.
          </p>

          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2 flex items-center gap-1.5">
              <Paperclip size={12} weight="bold" /> Attach Player Dossier <span className="text-[#666] normal-case tracking-normal font-normal">(optional)</span>
            </label>
            {sharedPlayers.length === 0 ? (
              <div data-testid="no-shared-players" className="text-xs text-[#666] bg-[#0A0A0A] border border-white/10 px-3 py-3">
                You don't have any public player dossiers yet. Share a player profile from their dossier page first, then come back here to attach it.
              </div>
            ) : (
              <select data-testid="dossier-attach-select"
                value={attachToken} onChange={(e) => setAttachToken(e.target.value)}
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-3 focus:border-[#10B981] focus:outline-none text-sm">
                <option value="">— No attachment —</option>
                {sharedPlayers.map(p => (
                  <option key={p.id} value={p.share_token}>
                    #{p.number ?? '—'} {p.name}{p.position ? ` (${p.position})` : ''}
                  </option>
                ))}
              </select>
            )}
            {attachToken && (
              <p data-testid="attach-confirm" className="text-[11px] text-[#10B981] mt-1">
                ✓ Dossier link will be added at the end of your message.
              </p>
            )}
          </div>

          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Your Message</label>
            <textarea data-testid="interest-message-input"
              value={message} onChange={(e) => setMessage(e.target.value)}
              rows={6}
              placeholder={`Hi! I'm ${user?.name || 'a coach'}. I have a player in our ${new Date().getFullYear() + 1} class who could be a great fit. Here's why...`}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-3 focus:border-[#10B981] focus:outline-none text-sm resize-y" required />
            <p className="text-[11px] text-[#666] mt-1">{message.length} / 5000 characters</p>
          </div>

          {error && (
            <div data-testid="interest-error" className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm flex items-start gap-2">
              <Warning size={18} weight="fill" className="flex-shrink-0 mt-0.5" /> <span>{error}</span>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            <button type="button" onClick={onClose}
              className="border border-white/10 text-white py-3 px-6 font-bold tracking-wider uppercase text-xs hover:bg-[#1F1F1F] transition-colors">
              Cancel
            </button>
            <button data-testid="interest-submit-btn" type="submit" disabled={sending}
              className="flex-1 flex items-center justify-center gap-2 bg-[#10B981] hover:bg-[#0EA975] text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors disabled:opacity-50">
              <PaperPlaneRight size={16} weight="fill" /> {sending ? 'Sending...' : 'Send Interest'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ExpressInterestModal;
