import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, At, FilmStrip, Check, EnvelopeOpen, Clock } from '@phosphor-icons/react';

const timeAgo = (iso) => {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
};

const MentionsInbox = () => {
  const navigate = useNavigate();
  const [mentions, setMentions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [markingAll, setMarkingAll] = useState(false);

  const fetchMentions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/coach-network/mentions`, { headers: getAuthHeader() });
      setMentions(res.data);
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load mentions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchMentions(); }, [fetchMentions]);

  const markRead = async (id) => {
    try {
      await axios.post(`${API}/coach-network/mentions/${id}/read`, {}, { headers: getAuthHeader() });
      setMentions((prev) => prev.map((m) => (m.id === id ? { ...m, read_at: new Date().toISOString() } : m)));
    } catch { /* silent — UI can retry on next load */ }
  };

  const markAllRead = async () => {
    setMarkingAll(true);
    try {
      await axios.post(`${API}/coach-network/mentions/read-all`, {}, { headers: getAuthHeader() });
      const now = new Date().toISOString();
      setMentions((prev) => prev.map((m) => (m.read_at ? m : { ...m, read_at: now })));
    } catch { /* silent */ }
    finally { setMarkingAll(false); }
  };

  const openReel = (mention) => {
    if (!mention.read_at) markRead(mention.id);
    window.open(`/clips/${mention.reel_share_token}`, '_blank', 'noopener');
  };

  const unreadCount = mentions.filter((m) => !m.read_at).length;

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <button data-testid="mentions-back-btn" onClick={() => navigate('/')}
              className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10 flex-shrink-0">
              <ArrowLeft size={18} />
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <At size={20} weight="bold" className="text-[#A855F7] flex-shrink-0" />
              <h1 className="text-xl sm:text-2xl font-bold tracking-wider uppercase truncate" style={{ fontFamily: 'Bebas Neue' }}>
                Mentions
              </h1>
              {unreadCount > 0 && (
                <span data-testid="unread-badge"
                  className="text-[10px] tracking-wider uppercase font-bold px-2 py-0.5 bg-[#A855F7] text-white">
                  {unreadCount}
                </span>
              )}
            </div>
          </div>
          {unreadCount > 0 && (
            <button data-testid="mark-all-read-btn" onClick={markAllRead} disabled={markingAll}
              className="flex items-center gap-1.5 text-[10px] sm:text-xs text-[#A855F7] hover:text-white font-bold tracking-wider uppercase px-2 sm:px-3 py-1.5 border border-[#A855F7]/30 hover:bg-[#A855F7]/10 transition-colors disabled:opacity-50 flex-shrink-0">
              <Check size={12} weight="bold" />
              <span className="hidden sm:inline">Mark all read</span>
              <span className="sm:hidden">Clear</span>
            </button>
          )}
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        {error && (
          <div data-testid="mentions-error" className="bg-[#1F0E0E] border border-[#EF4444]/30 p-4 mb-6 text-sm text-[#EF4444]">
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-sm text-[#666] text-center py-16">Loading…</p>
        ) : mentions.length === 0 ? (
          <div className="text-center py-16">
            <EnvelopeOpen size={48} weight="thin" className="text-[#333] mx-auto mb-4" />
            <p className="text-sm text-[#A3A3A3] mb-2">No mentions yet</p>
            <p className="text-xs text-[#666] max-w-sm mx-auto leading-relaxed">
              When another coach tags you in a shared clip reel, it'll appear here and you'll get an email.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {mentions.map((m) => {
              const unread = !m.read_at;
              return (
                <div key={m.id} data-testid={`mention-row-${m.id}`}
                  className={`border p-4 sm:p-5 transition-colors cursor-pointer ${
                    unread
                      ? 'bg-[#1A0F2B] border-[#A855F7]/40 hover:border-[#A855F7]/70'
                      : 'bg-[#141414] border-white/5 hover:border-white/20'
                  }`}
                  onClick={() => openReel(m)}>
                  <div className="flex items-start gap-3">
                    {unread && (
                      <span className="flex-shrink-0 w-2 h-2 bg-[#A855F7] rounded-full mt-2" aria-label="Unread" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-[11px] sm:text-xs font-bold tracking-[0.2em] uppercase text-[#A855F7]">
                          <At size={10} weight="bold" className="inline -mt-0.5 mr-0.5" />
                          {m.mentioner_name}
                        </span>
                        <span className="text-[10px] text-[#666] flex items-center gap-1">
                          <Clock size={10} />{timeAgo(m.created_at)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mb-2">
                        <FilmStrip size={14} weight="bold" className="text-[#A3A3A3] flex-shrink-0" />
                        <span className="text-sm sm:text-base font-semibold text-white truncate">{m.reel_title}</span>
                        <span className="text-[10px] text-[#666] tracking-wider uppercase flex-shrink-0">
                          {m.reel_clip_count} clip{m.reel_clip_count !== 1 ? 's' : ''}
                        </span>
                      </div>
                      {m.reel_description && (
                        <p className="text-xs text-[#A3A3A3] italic line-clamp-2 mb-2 leading-relaxed">
                          "{m.reel_description}"
                        </p>
                      )}
                      <div className="flex gap-2 flex-wrap mt-2">
                        <button data-testid={`open-reel-${m.id}-btn`} type="button"
                          onClick={(e) => { e.stopPropagation(); openReel(m); }}
                          className="text-[10px] sm:text-xs font-bold tracking-wider uppercase px-3 py-1.5 bg-[#A855F7] hover:bg-[#9333EA] text-white transition-colors">
                          Watch Reel →
                        </button>
                        {unread && (
                          <button data-testid={`mark-read-${m.id}-btn`} type="button"
                            onClick={(e) => { e.stopPropagation(); markRead(m.id); }}
                            className="text-[10px] sm:text-xs font-bold tracking-wider uppercase px-3 py-1.5 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors">
                            Mark read
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
};

export default MentionsInbox;
