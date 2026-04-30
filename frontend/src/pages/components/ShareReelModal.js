import { FilmStrip } from '@phosphor-icons/react';

const ShareReelModal = ({
  collectionModalOpen,
  setCollectionModalOpen,
  collectionShare,
  selectedClips,
  collectionTitle,
  setCollectionTitle,
  handleCreateCollection,
  creatingCollection,
  collectionUrl,
  copyCollectionUrl,
  collectionCopied,
}) => {
  if (!collectionModalOpen) return null;
  return (
    <div data-testid="reel-modal-overlay" onClick={() => !creatingCollection && setCollectionModalOpen(false)}
      className="fixed inset-0 bg-black/70 z-[200] overflow-y-auto p-4 sm:flex sm:items-center sm:justify-center">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-white/10 max-w-lg w-full p-6 rounded-lg mx-auto my-4 sm:my-0">
        <div className="flex items-center gap-2 mb-2">
          <FilmStrip size={22} weight="bold" className="text-[#A855F7]" />
          <h3 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
            {collectionShare ? 'Reel Ready' : 'Share Clip Reel'}
          </h3>
        </div>

        {!collectionShare ? (
          <>
            <p className="text-sm text-[#A3A3A3] mb-4">
              Bundle <strong className="text-white">{selectedClips.length} selected clip{selectedClips.length === 1 ? '' : 's'}</strong> into
              one shareable reel page with a built-in playlist.
            </p>
            <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Reel Title</label>
            <input data-testid="reel-title-input" type="text"
              value={collectionTitle}
              onChange={(e) => setCollectionTitle(e.target.value)}
              placeholder={`e.g., 1st Half Highlights, Ethan's Goals…`}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 mb-5 focus:border-[#A855F7] focus:outline-none rounded" />
            <div className="flex gap-3">
              <button data-testid="create-reel-btn" onClick={handleCreateCollection} disabled={creatingCollection}
                className="flex-1 bg-[#A855F7] hover:bg-[#9333EA] disabled:opacity-50 text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors rounded">
                {creatingCollection ? 'Creating…' : 'Create Reel'}
              </button>
              <button type="button" onClick={() => setCollectionModalOpen(false)} disabled={creatingCollection}
                className="px-5 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] text-xs font-bold uppercase rounded">
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-[#A3A3A3] mb-4">
              Reel <strong className="text-white">"{collectionShare.title}"</strong> with {selectedClips.length} clip{selectedClips.length === 1 ? '' : 's'} is ready to share.
            </p>
            <div className="flex items-center gap-2 mb-2">
              <div className="flex-1 bg-[#0A0A0A] border border-white/10 text-[#A855F7] px-3 py-2.5 text-xs font-mono truncate select-all rounded">
                {collectionUrl}
              </div>
              <button data-testid="copy-reel-url-btn" onClick={copyCollectionUrl}
                className={`px-4 py-2.5 text-xs font-bold tracking-wider uppercase rounded transition-colors ${
                  collectionCopied ? 'bg-[#10B981] text-black' : 'bg-[#A855F7] hover:bg-[#9333EA] text-white'
                }`}>
                {collectionCopied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="text-[10px] text-[#10B981] tracking-[0.15em] uppercase font-bold mb-3 flex items-center gap-1.5">
              ✓ Smart link — unfurls with rich preview
            </div>
            <a data-testid="reel-preview-link"
              href={`${window.location.origin}/clips/${collectionShare.share_token}`}
              target="_blank" rel="noopener noreferrer"
              className="block text-xs text-[#A3A3A3] hover:text-white underline underline-offset-2 mb-5">
              Open reel in new tab →
            </a>
            <button onClick={() => setCollectionModalOpen(false)}
              className="w-full border border-white/10 text-white py-3 text-xs font-bold tracking-wider uppercase hover:bg-[#1F1F1F] rounded transition-colors">
              Done
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default ShareReelModal;
