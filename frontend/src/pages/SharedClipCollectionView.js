import { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Play, FilmStrip, CalendarBlank, Trophy, Link as LinkIcon, Copy, Check } from '@phosphor-icons/react';

const SharedClipCollectionView = () => {
  const { shareToken } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [copied, setCopied] = useState(false);
  const videoRef = useRef(null);

  useEffect(() => {
    axios.get(`${API}/shared/clip-collection/${shareToken}`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.status === 404 ? 'notfound' : 'error'));
  }, [shareToken]);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.load();
      videoRef.current.play().catch(() => {});
    }
  }, [activeIndex]);

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const handleCopy = async () => {
    const url = `${window.location.origin}/api/og/clip-collection/${shareToken}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = url; document.body.appendChild(ta);
      ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (error === 'notfound') {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white flex items-center justify-center px-6">
        <div className="text-center">
          <LinkIcon size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Reel Unavailable</h1>
          <p className="text-[#A3A3A3]">This clip-reel link has been revoked or never existed.</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const { collection, owner, clips } = data;
  const active = clips[activeIndex];

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="shared-clip-collection">
      <header className="bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <FilmStrip size={28} weight="fill" className="text-[#007AFF] flex-shrink-0" />
            <div className="min-w-0">
              <div className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#007AFF]">Clip Reel</div>
              <h1 className="text-xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>{collection.title}</h1>
            </div>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <span className="text-xs text-[#666] hidden sm:block">Shared by {owner}</span>
            <button data-testid="copy-collection-btn" onClick={handleCopy}
              className={`flex items-center gap-2 px-3 py-2 text-xs font-bold tracking-wider uppercase transition-colors ${
                copied ? 'bg-[#10B981]/20 text-[#10B981]' : 'bg-[#007AFF]/10 text-[#007AFF] hover:bg-[#007AFF]/20'
              }`}>
              {copied ? <><Check size={12} weight="bold" /> Copied</> : <><Copy size={12} weight="bold" /> Copy Link</>}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Player area */}
        <div className="lg:col-span-2">
          <div className="bg-black overflow-hidden">
            {active && (
              <video ref={videoRef} key={active.id} data-testid="active-clip-video"
                controls autoPlay
                className="w-full aspect-video"
                src={`${API}/shared/clip/${active.share_token}/video`}
                preload="auto" />
            )}
          </div>
          {active && (
            <div className="bg-[#141414] border border-white/10 p-5 mt-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{active.title}</h2>
                  {active.match && (
                    <div className="flex items-center gap-3 text-sm text-[#A3A3A3] mt-1.5">
                      <span className="flex items-center gap-1.5">
                        <Trophy size={14} className="text-[#007AFF]" />
                        {active.match.team_home} vs {active.match.team_away}
                      </span>
                      {active.match.date && (
                        <span className="flex items-center gap-1">
                          <CalendarBlank size={12} /> {active.match.date}
                        </span>
                      )}
                    </div>
                  )}
                  <div className="flex items-center gap-2 text-[10px] text-[#666] mt-2 tracking-wider uppercase">
                    <span className="bg-white/5 px-2 py-0.5">{active.clip_type}</span>
                    <span>{formatTime(active.start_time)} — {formatTime(active.end_time)}</span>
                  </div>
                </div>
                <span className="text-xs text-[#666] flex-shrink-0">
                  Clip {activeIndex + 1} of {clips.length}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Playlist */}
        <aside className="space-y-2">
          <div className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">
            Playlist ({clips.length})
          </div>
          <div className="space-y-2 max-h-[70vh] overflow-y-auto pr-1">
            {clips.map((c, i) => (
              <button key={c.id} data-testid={`playlist-item-${i}`}
                onClick={() => setActiveIndex(i)}
                className={`w-full text-left p-3 border transition-colors flex items-start gap-3 ${
                  i === activeIndex
                    ? 'bg-[#007AFF]/10 border-[#007AFF]/40'
                    : 'bg-[#141414] border-white/10 hover:border-white/30'
                }`}>
                <div className="w-10 h-10 flex-shrink-0 bg-[#0A0A0A] border border-white/10 flex items-center justify-center">
                  <Play size={16} weight={i === activeIndex ? 'fill' : 'regular'}
                    className={i === activeIndex ? 'text-[#007AFF]' : 'text-[#666]'} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate">{c.title || 'Untitled'}</div>
                  <div className="text-[10px] text-[#666] tracking-wider uppercase mt-0.5">
                    {c.clip_type} • {formatTime(c.end_time - c.start_time)}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </aside>
      </main>

      <footer className="border-t border-white/5 px-6 py-4 text-center mt-8">
        <p className="text-xs text-[#555]">
          Powered by <span className="text-[#007AFF]">Soccer Scout</span>
        </p>
      </footer>
    </div>
  );
};

export default SharedClipCollectionView;
