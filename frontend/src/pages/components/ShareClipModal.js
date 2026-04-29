import { ShareNetwork } from '@phosphor-icons/react';

const ShareClipModal = ({
  sharingClip,
  setSharingClip,
  copyClipShareLink,
  clipShareCopied,
  shareClipTo,
  handleRevokeClipShare,
}) => {
  if (!sharingClip) return null;
  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-6 z-50">
      <div className="bg-[#141414] border border-white/10 w-full max-w-md p-8 rounded-lg">
        <div className="flex items-center gap-3 mb-5">
          <ShareNetwork size={24} weight="bold" className="text-[#A855F7]" />
          <h3 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Share Clip</h3>
        </div>
        <p className="text-sm text-[#A3A3A3] mb-4">
          <strong className="text-white">{sharingClip.title}</strong> — anyone with the link can view this clip.
        </p>

        <div className="flex items-center gap-2 mb-2">
          <div className="flex-1 bg-[#0A0A0A] border border-white/10 text-[#007AFF] px-3 py-2.5 text-xs font-mono truncate select-all rounded">
            {window.location.origin}/api/og/clip/{sharingClip.share_token}
          </div>
          <button data-testid="copy-clip-share-btn" onClick={copyClipShareLink}
            className={`px-4 py-2.5 font-bold tracking-wider uppercase text-xs transition-colors rounded ${
              clipShareCopied ? 'bg-[#4ADE80] text-black' : 'bg-[#007AFF] hover:bg-[#005bb5] text-white'
            }`}>
            {clipShareCopied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <div className="text-[10px] text-[#10B981] tracking-[0.15em] uppercase font-bold mb-5 flex items-center gap-1.5">
          ✓ Smart link — unfurls with rich preview in WhatsApp, Slack, Twitter
        </div>

        <div className="grid grid-cols-2 gap-2 mb-5">
          <button data-testid="share-clip-facebook" onClick={() => shareClipTo('facebook')}
            className="flex items-center gap-2 px-3 py-2.5 bg-[#1877F2]/10 border border-[#1877F2]/20 text-[#1877F2] text-xs font-medium rounded hover:bg-[#1877F2]/20 transition-colors">
            <div className="w-5 h-5 rounded bg-[#1877F2] text-white text-[8px] font-bold flex items-center justify-center">FB</div>
            Facebook
          </button>
          <button data-testid="share-clip-instagram" onClick={() => shareClipTo('instagram')}
            className="flex items-center gap-2 px-3 py-2.5 bg-[#E4405F]/10 border border-[#E4405F]/20 text-[#E4405F] text-xs font-medium rounded hover:bg-[#E4405F]/20 transition-colors">
            <div className="w-5 h-5 rounded bg-[#E4405F] text-white text-[8px] font-bold flex items-center justify-center">IG</div>
            Instagram
          </button>
          <button data-testid="share-clip-youtube" onClick={() => shareClipTo('youtube')}
            className="flex items-center gap-2 px-3 py-2.5 bg-[#FF0000]/10 border border-[#FF0000]/20 text-[#FF0000] text-xs font-medium rounded hover:bg-[#FF0000]/20 transition-colors">
            <div className="w-5 h-5 rounded bg-[#FF0000] text-white text-[8px] font-bold flex items-center justify-center">YT</div>
            YouTube
          </button>
          <button data-testid="share-clip-sms" onClick={() => shareClipTo('sms')}
            className="flex items-center gap-2 px-3 py-2.5 bg-[#4ADE80]/10 border border-[#4ADE80]/20 text-[#4ADE80] text-xs font-medium rounded hover:bg-[#4ADE80]/20 transition-colors">
            <div className="w-5 h-5 rounded bg-[#4ADE80] text-black text-[8px] font-bold flex items-center justify-center">SM</div>
            Text / SMS
          </button>
        </div>

        <button data-testid="revoke-clip-share-btn" onClick={handleRevokeClipShare}
          className="w-full bg-transparent border border-[#EF4444]/30 text-[#EF4444] py-2 text-xs font-bold tracking-wider uppercase hover:bg-[#EF4444]/10 transition-colors rounded mb-2">
          Revoke Share Link
        </button>
        <button data-testid="close-clip-share-modal" onClick={() => setSharingClip(null)}
          className="w-full bg-transparent border border-white/10 text-white py-2.5 text-xs font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors rounded">
          Close
        </button>
      </div>
    </div>
  );
};

export default ShareClipModal;
