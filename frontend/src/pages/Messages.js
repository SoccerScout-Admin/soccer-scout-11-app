import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import {
  ArrowLeft, ChatCircle, PaperPlaneRight, EnvelopeSimple,
} from '@phosphor-icons/react';

const formatRelative = (iso) => {
  if (!iso) return '';
  const then = new Date(iso);
  const diff = Math.floor((Date.now() - then.getTime()) / 1000);
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`;
  return then.toLocaleDateString();
};

const Messages = () => {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const user = getCurrentUser();
  const [threads, setThreads] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [reply, setReply] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef(null);

  const fetchThreads = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/messages/threads`, { headers: getAuthHeader() });
      setThreads(res.data || []);
    } catch {
      setThreads([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchThread = useCallback(async (id) => {
    try {
      const res = await axios.get(`${API}/messages/threads/${id}`, { headers: getAuthHeader() });
      setActiveThread(res.data);
      // Mark read so the badge clears
      axios.post(`${API}/messages/threads/${id}/read`, {}, { headers: getAuthHeader() })
        .then(() => fetchThreads()).catch(() => {});
    } catch {
      setActiveThread(null);
    }
  }, [fetchThreads]);

  useEffect(() => { fetchThreads(); }, [fetchThreads]);
  useEffect(() => { if (threadId) fetchThread(threadId); }, [threadId, fetchThread]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [activeThread?.messages?.length]);

  const sendReply = async (e) => {
    e.preventDefault();
    if (!activeThread || !reply.trim()) return;
    setSending(true);
    try {
      await axios.post(
        `${API}/messages/threads/${activeThread.id}/reply`,
        { body: reply.trim() },
        { headers: getAuthHeader() },
      );
      setReply('');
      await fetchThread(activeThread.id);
      await fetchThreads();
    } catch (err) {
      alert('Failed to send: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSending(false);
    }
  };

  const otherParticipant = (thread) => {
    return (thread?.participants || []).find(p => p.id !== user?.id) || { name: 'Unknown' };
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-40 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-3">
          <button data-testid="messages-back-btn" onClick={() => navigate('/')}
            className="p-2 border border-white/10 hover:bg-[#1F1F1F] transition-colors">
            <ArrowLeft size={20} className="text-white" />
          </button>
          <div>
            <h1 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Messages</h1>
            <p className="text-xs text-[#A3A3A3]">Direct conversations with scouts and coaches</p>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto h-[calc(100vh-72px)]">
        <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] h-full divide-x divide-white/10">
          {/* Thread list */}
          <aside className={`${activeThread ? 'hidden md:block' : 'block'} overflow-y-auto`}>
            {loading ? (
              <p className="text-center py-10 text-[#A3A3A3]">Loading...</p>
            ) : threads.length === 0 ? (
              <div className="text-center py-20 px-4">
                <ChatCircle size={48} className="text-[#A3A3A3] mx-auto mb-3" />
                <p className="text-sm text-[#A3A3A3]">No conversations yet.</p>
                <p className="text-xs text-[#666] mt-1">When a scout or coach messages you, the thread shows up here.</p>
              </div>
            ) : (
              <div data-testid="thread-list">
                {threads.map(t => {
                  const other = otherParticipant(t);
                  const isActive = activeThread?.id === t.id;
                  return (
                    <button key={t.id} data-testid={`thread-${t.id}`}
                      onClick={() => navigate(`/messages/${t.id}`)}
                      className={`w-full text-left px-4 py-4 border-b border-white/5 transition-colors ${
                        isActive ? 'bg-[#1F1F1F]' : 'hover:bg-[#1A1A1A]'
                      }`}>
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <span className="text-sm font-bold text-white truncate">{other.name}</span>
                        <span className="text-[10px] text-[#A3A3A3] flex-shrink-0">{formatRelative(t.last_message_at)}</span>
                      </div>
                      {t.topic && <p className="text-[11px] text-[#10B981] uppercase tracking-wider mb-1">{t.topic}</p>}
                      <p className="text-xs text-[#A3A3A3] truncate">{t.last_message_preview || 'No messages yet'}</p>
                      {t.my_unread > 0 && (
                        <span data-testid={`unread-${t.id}`}
                          className="inline-block mt-1 text-[10px] bg-[#10B981] text-white px-2 py-0.5 font-bold tracking-wider uppercase">
                          {t.my_unread} new
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </aside>

          {/* Active thread */}
          <section className={`${activeThread ? 'flex' : 'hidden md:flex'} flex-col`}>
            {!activeThread ? (
              <div className="flex-1 flex flex-col items-center justify-center text-[#A3A3A3]">
                <EnvelopeSimple size={56} className="mb-3" />
                <p className="text-sm">Select a conversation to read</p>
              </div>
            ) : (
              <>
                <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
                  <div>
                    <button onClick={() => navigate('/messages')} className="md:hidden text-xs text-[#A3A3A3] mb-1">← Back to inbox</button>
                    <h2 className="text-xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>{otherParticipant(activeThread).name}</h2>
                    {activeThread.topic && <p className="text-[11px] text-[#10B981] uppercase tracking-wider">{activeThread.topic}</p>}
                  </div>
                </div>

                <div ref={scrollRef} data-testid="messages-list" className="flex-1 overflow-y-auto p-5 space-y-3">
                  {(activeThread.messages || []).map(m => {
                    const mine = m.sender_id === user?.id;
                    return (
                      <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[80%] px-4 py-3 ${
                          mine ? 'bg-[#10B981] text-white' : 'bg-[#1F1F1F] text-[#EAEAEA] border border-white/5'
                        }`}>
                          <p className="text-sm whitespace-pre-wrap leading-relaxed">{m.body}</p>
                          <p className={`text-[10px] mt-1 ${mine ? 'text-white/60' : 'text-[#666]'}`}>{formatRelative(m.created_at)}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <form onSubmit={sendReply} className="border-t border-white/10 p-4 flex items-center gap-3">
                  <input data-testid="reply-input"
                    value={reply} onChange={(e) => setReply(e.target.value)}
                    placeholder="Type a reply..."
                    className="flex-1 bg-[#0A0A0A] border border-white/10 text-white px-3 py-3 focus:border-[#10B981] focus:outline-none text-sm" />
                  <button data-testid="reply-send-btn" type="submit" disabled={sending || !reply.trim()}
                    className="flex items-center gap-2 bg-[#10B981] hover:bg-[#0EA975] text-white py-3 px-5 font-bold tracking-wider uppercase text-xs transition-colors disabled:opacity-50">
                    <PaperPlaneRight size={14} weight="fill" /> Send
                  </button>
                </form>
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
};

export default Messages;
