import { FilmStrip, At, X, Check, UserCircle } from '@phosphor-icons/react';
import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';

/**
 * Reel share modal with:
 * - Title + description
 * - @-mentions coach directory autocomplete (fetches /coach-network/mentionable-coaches)
 * - On create, returns shareable URL and reports mention notifications sent
 */
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
  description,
  setDescription,
  mentionedCoaches,
  setMentionedCoaches,
}) => {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const debounceRef = useRef(null);

  const fetchSuggestions = useCallback((q) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoadingSuggestions(true);
      try {
        const res = await axios.get(`${API}/coach-network/mentionable-coaches`, {
          headers: getAuthHeader(),
          params: q ? { q } : {},
        });
        setSuggestions(res.data);
      } catch (err) {
        console.warn('[share-reel] fetch mentionable coaches failed:', err);
        setSuggestions([]);
      } finally {
        setLoadingSuggestions(false);
      }
    }, 250);
  }, []);

  useEffect(() => {
    if (!collectionModalOpen || collectionShare) return;
    fetchSuggestions(query);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [collectionModalOpen, collectionShare, query, fetchSuggestions]);

  const toggleMention = (coach) => {
    setMentionedCoaches((prev) => {
      const exists = prev.find((c) => c.id === coach.id);
      if (exists) return prev.filter((c) => c.id !== coach.id);
      return [...prev, { id: coach.id, name: coach.name, email: coach.email }];
    });
  };

  if (!collectionModalOpen) return null;
  return (
    <div data-testid="reel-modal-overlay" onClick={() => !creatingCollection && setCollectionModalOpen(false)}
      className="fixed inset-0 bg-black/70 z-[200] overflow-y-auto p-4 sm:flex sm:items-start sm:justify-center sm:py-12">
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
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 mb-4 focus:border-[#A855F7] focus:outline-none rounded" />

            <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Description (optional)</label>
            <textarea data-testid="reel-description-input"
              value={description || ''}
              onChange={(e) => setDescription?.(e.target.value)}
              rows={2}
              maxLength={600}
              placeholder="What should mentioned coaches look for? (appears in the mention email)"
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-2 text-sm mb-4 focus:border-[#A855F7] focus:outline-none rounded resize-none" />

            {/* @Mentions */}
            <label className="flex items-center gap-1.5 text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">
              <At size={12} weight="bold" /> Mention Coaches (optional)
            </label>

            {mentionedCoaches?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2" data-testid="mentioned-chips">
                {mentionedCoaches.map((c) => (
                  <span key={c.id} data-testid={`mention-chip-${c.id}`}
                    className="inline-flex items-center gap-1 bg-[#A855F7]/15 border border-[#A855F7]/40 text-[#A855F7] text-xs px-2 py-1 rounded">
                    @{c.name || c.email}
                    <button onClick={() => toggleMention(c)} type="button"
                      className="hover:text-white" data-testid={`remove-mention-${c.id}`}>
                      <X size={10} weight="bold" />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <input data-testid="mention-search-input" type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type to search coaches…"
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 text-xs mb-2 focus:border-[#A855F7] focus:outline-none rounded" />

            {suggestions.length > 0 && (
              <div data-testid="mention-suggestions"
                className="max-h-40 overflow-y-auto bg-[#0A0A0A] border border-white/5 rounded mb-4">
                {suggestions.slice(0, 8).map((s) => {
                  const picked = mentionedCoaches?.some((m) => m.id === s.id);
                  return (
                    <button key={s.id} type="button" onClick={() => toggleMention(s)}
                      data-testid={`mention-suggestion-${s.id}`}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors ${picked ? 'bg-[#A855F7]/15' : 'hover:bg-white/5'}`}>
                      <UserCircle size={16} className="text-[#A3A3A3] flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-white font-medium truncate">{s.name || s.email}</span>
                          {s.active && <span className="text-[9px] text-[#10B981]">●</span>}
                        </div>
                        {s.name && <span className="text-[10px] text-[#666] truncate block">{s.email}</span>}
                      </div>
                      {picked && <Check size={14} weight="bold" className="text-[#A855F7] flex-shrink-0" />}
                    </button>
                  );
                })}
              </div>
            )}
            {loadingSuggestions && <p className="text-[10px] text-[#666] mb-3">Searching coaches…</p>}
            {!loadingSuggestions && query && suggestions.length === 0 && (
              <p className="text-[10px] text-[#666] mb-3">No matching coaches. Try a different name or email.</p>
            )}

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
            <p className="text-sm text-[#A3A3A3] mb-2">
              Reel <strong className="text-white">"{collectionShare.title}"</strong> with {selectedClips.length} clip{selectedClips.length === 1 ? '' : 's'} is ready to share.
            </p>
            {collectionShare.mentions_sent > 0 && (
              <div data-testid="mentions-sent-banner"
                className="bg-[#A855F7]/10 border border-[#A855F7]/30 text-[#A855F7] text-xs px-3 py-2 mb-3 rounded">
                <At size={12} weight="bold" className="inline mr-1" />
                Notified {collectionShare.mentions_sent} coach{collectionShare.mentions_sent === 1 ? '' : 'es'} via email
                {collectionShare.mentions_skipped > 0 && ` (${collectionShare.mentions_skipped} skipped — already emailed or no address)`}
              </div>
            )}
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
