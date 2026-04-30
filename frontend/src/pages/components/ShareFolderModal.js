import { ShareNetwork, Copy, Check } from '@phosphor-icons/react';

const ShareFolderModal = ({ open, sharingFolder, onClose, onCopy, onRevoke, copied }) => {
  if (!open || !sharingFolder) return null;
  return (
    <div className="fixed inset-0 bg-black/80 overflow-y-auto z-50 p-4 sm:p-6" data-testid="share-folder-modal">
      <div className="bg-[#141414] border border-white/10 w-full max-w-md p-6 sm:p-8 mx-auto my-4 sm:my-8">
        <div className="flex items-center gap-3 mb-6">
          <ShareNetwork size={28} className="text-[#4ADE80]" />
          <h3 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Share Folder</h3>
        </div>
        {sharingFolder.share_token ? (
          <div>
            <p className="text-sm text-[#A3A3A3] mb-4">
              Anyone with this link can view <strong className="text-white">{sharingFolder.name}</strong> and its matches, analyses, clips, and annotations — no login required.
            </p>
            <div className="flex items-center gap-2 mb-2">
              <div className="flex-1 bg-[#0A0A0A] border border-white/10 text-[#007AFF] px-4 py-3 text-sm font-mono truncate select-all">
                {window.location.origin}/api/og/folder/{sharingFolder.share_token}
              </div>
              <button data-testid="copy-share-link-btn" onClick={onCopy}
                className={`px-4 py-3 font-bold tracking-wider uppercase transition-colors flex items-center gap-2 text-sm ${
                  copied ? 'bg-[#4ADE80] text-black' : 'bg-[#007AFF] hover:bg-[#005bb5] text-white'
                }`}>
                {copied ? <><Check size={16} weight="bold" /> Copied</> : <><Copy size={16} /> Copy</>}
              </button>
            </div>
            <div className="text-[10px] text-[#10B981] tracking-[0.15em] uppercase font-bold mb-3 flex items-center gap-1.5">
              <Check size={11} weight="bold" /> Smart link — unfurls with rich preview in WhatsApp, Slack, Twitter
            </div>
            <a data-testid="folder-preview-link" target="_blank" rel="noopener noreferrer"
              href={`${window.location.origin}/shared/${sharingFolder.share_token}`}
              className="block text-xs text-[#A3A3A3] hover:text-white underline underline-offset-2 mb-6">
              Open public folder in new tab →
            </a>
            <button data-testid="revoke-share-btn" onClick={onRevoke}
              className="w-full bg-transparent border border-[#EF4444]/30 text-[#EF4444] py-2 text-xs font-bold tracking-wider uppercase hover:bg-[#EF4444]/10 transition-colors">
              Revoke Share Link
            </button>
          </div>
        ) : (
          <p className="text-sm text-[#A3A3A3]">Sharing has been revoked for this folder.</p>
        )}
        <button data-testid="close-share-modal-btn" onClick={onClose}
          className="w-full mt-4 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
          Close
        </button>
      </div>
    </div>
  );
};

export default ShareFolderModal;
