import { useState } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { ShareNetwork, Copy, Check, X, WhatsappLogo, TwitterLogo, EnvelopeSimple } from '@phosphor-icons/react';

const ShareRecapModal = ({ open, matchId, onClose, onTokenChange, initialToken = null }) => {
  const [shareToken, setShareToken] = useState(initialToken);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;

  const url = shareToken ? `${window.location.origin}/api/og/match-recap/${shareToken}` : '';
  const spaUrl = shareToken ? `${window.location.origin}/match-recap/${shareToken}` : '';

  const _fallbackCopy = (text) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  };

  const _toggleShare = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await axios.post(`${API}/matches/${matchId}/share-recap`, {}, { headers: getAuthHeader() });
      if (res.data.status === 'shared') {
        setShareToken(res.data.share_token);
        if (onTokenChange) onTokenChange(res.data.share_token);
      } else {
        setShareToken(null);
        if (onTokenChange) onTokenChange(null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update share link');
    } finally {
      setBusy(false);
    }
  };

  const _copyLink = async () => {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      _fallbackCopy(url);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const _shareTo = (platform) => {
    const text = 'Match recap on Soccer Scout 11';
    const links = {
      whatsapp: `https://wa.me/?text=${encodeURIComponent(`${text}: ${url}`)}`,
      twitter: `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
      email: `mailto:?subject=${encodeURIComponent(text)}&body=${encodeURIComponent(`${text}: ${url}`)}`,
    };
    window.open(links[platform], '_blank', 'width=600,height=500');
  };

  return (
    <div data-testid="share-recap-modal-overlay" onClick={onClose}
      className="fixed inset-0 bg-black/70 z-[200] flex items-center justify-center px-4">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-[#A855F7]/30 w-full max-w-md p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <ShareNetwork size={24} weight="bold" className="text-[#A855F7]" />
            <h3 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
              Share Match Recap
            </h3>
          </div>
          <button data-testid="close-share-recap-btn" onClick={onClose} className="p-1 text-[#A3A3A3] hover:text-white">
            <X size={20} />
          </button>
        </div>

        {!shareToken ? (
          <div>
            <p className="text-sm text-[#A3A3A3] mb-5 leading-relaxed">
              Generate a public link with a rich preview card (logo, score, and AI recap excerpt).
              Anyone with the link can view the recap — no login required.
            </p>
            <button data-testid="enable-share-recap-btn" onClick={_toggleShare} disabled={busy}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-[#A855F7] to-[#9333EA] text-white py-3 font-bold tracking-wider uppercase text-xs hover:opacity-90 disabled:opacity-50 transition-opacity">
              {busy ? (
                <><div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" /> Generating…</>
              ) : (
                <><ShareNetwork size={14} weight="bold" /> Enable Share Link</>
              )}
            </button>
            {error && <div className="mt-3 text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 px-3 py-2">{error}</div>}
          </div>
        ) : (
          <div>
            <p className="text-xs text-[#10B981] mb-3 flex items-center gap-1.5 tracking-wider uppercase font-bold">
              <Check size={12} weight="bold" /> Share link active — Smart preview enabled
            </p>
            <div className="flex items-stretch gap-2 mb-3">
              <input data-testid="share-recap-link-input" type="text" readOnly value={url}
                className="flex-1 bg-[#0A0A0A] border border-white/10 text-[#007AFF] px-3 py-2 text-xs font-mono select-all min-w-0" />
              <button data-testid="copy-share-recap-btn" onClick={_copyLink}
                className={`px-3 py-2 text-[10px] font-bold tracking-wider uppercase transition-colors flex items-center gap-1 ${
                  copied ? 'bg-[#10B981] text-black' : 'bg-[#007AFF] hover:bg-[#005bb5] text-white'
                }`}>
                {copied ? <><Check size={12} weight="bold" /> Copied</> : <><Copy size={12} /> Copy</>}
              </button>
            </div>
            <a href={spaUrl} target="_blank" rel="noopener noreferrer" data-testid="open-recap-link"
              className="block text-[10px] text-[#A3A3A3] hover:text-white underline underline-offset-2 mb-4 truncate">
              Preview the public recap →
            </a>

            <div className="grid grid-cols-3 gap-2 mb-4">
              <button data-testid="share-recap-whatsapp" onClick={() => _shareTo('whatsapp')}
                className="flex flex-col items-center gap-1 py-3 bg-[#0A0A0A] border border-white/10 hover:border-[#25D366]/40 transition-colors">
                <WhatsappLogo size={20} className="text-[#25D366]" />
                <span className="text-[9px] font-bold tracking-wider uppercase text-[#A3A3A3]">WhatsApp</span>
              </button>
              <button data-testid="share-recap-twitter" onClick={() => _shareTo('twitter')}
                className="flex flex-col items-center gap-1 py-3 bg-[#0A0A0A] border border-white/10 hover:border-[#1DA1F2]/40 transition-colors">
                <TwitterLogo size={20} className="text-[#1DA1F2]" />
                <span className="text-[9px] font-bold tracking-wider uppercase text-[#A3A3A3]">Twitter</span>
              </button>
              <button data-testid="share-recap-email" onClick={() => _shareTo('email')}
                className="flex flex-col items-center gap-1 py-3 bg-[#0A0A0A] border border-white/10 hover:border-[#A855F7]/40 transition-colors">
                <EnvelopeSimple size={20} className="text-[#A855F7]" />
                <span className="text-[9px] font-bold tracking-wider uppercase text-[#A3A3A3]">Email</span>
              </button>
            </div>

            <button data-testid="revoke-share-recap-btn" onClick={_toggleShare} disabled={busy}
              className="w-full bg-transparent border border-[#EF4444]/30 text-[#EF4444] py-2 text-[10px] font-bold tracking-wider uppercase hover:bg-[#EF4444]/10 disabled:opacity-50 transition-colors">
              {busy ? 'Revoking…' : 'Revoke Share Link'}
            </button>
            {error && <div className="mt-3 text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 px-3 py-2">{error}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

export default ShareRecapModal;
