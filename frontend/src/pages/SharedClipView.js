import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Play, Trophy, CalendarBlank, ShareNetwork, Link as LinkIcon, Copy, Check } from '@phosphor-icons/react';

const SharedClipView = () => {
  const { shareToken } = useParams();
  const videoRef = useRef(null);
  const [clipData, setClipData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [showShareMenu, setShowShareMenu] = useState(false);

  const fetchClip = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/shared/clip/${shareToken}`);
      setClipData(res.data);
    } catch (err) {
      setError(err.response?.status === 404 ? 'This clip link is no longer available.' : 'Failed to load clip.');
    } finally {
      setLoading(false);
    }
  }, [shareToken]);

  useEffect(() => {
    fetchClip();
  }, [fetchClip]);

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const shareUrl = `${window.location.origin}/clip/${shareToken}`;

  const handleCopy = () => {
    try {
      navigator.clipboard.writeText(shareUrl).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }).catch(() => fallbackCopy());
    } catch {
      fallbackCopy();
    }
  };

  const fallbackCopy = () => {
    const ta = document.createElement('textarea');
    ta.value = shareUrl;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleNativeShare = () => {
    if (navigator.share) {
      navigator.share({
        title: clipData?.clip?.title || 'Soccer Clip',
        text: clipData?.match ? `${clipData.match.team_home} vs ${clipData.match.team_away} — ${clipData.clip.title}` : clipData?.clip?.title,
        url: shareUrl
      }).catch(() => {});
    } else {
      setShowShareMenu(!showShareMenu);
    }
  };

  const shareLinks = [
    { name: 'Facebook', icon: 'fb', color: '#1877F2', url: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}` },
    { name: 'Instagram', icon: 'ig', color: '#E4405F', url: shareUrl, note: 'Copy link to share on Instagram' },
    { name: 'YouTube', icon: 'yt', color: '#FF0000', url: shareUrl, note: 'Copy link to share on YouTube' },
    { name: 'Text / SMS', icon: 'sms', color: '#4ADE80', url: `sms:?body=${encodeURIComponent(`Check out this clip: ${shareUrl}`)}` },
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-10 h-10 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center text-center px-6 text-white">
        <div>
          <LinkIcon size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Clip Unavailable</h1>
          <p className="text-[#A3A3A3] mb-6">{error}</p>
        </div>
      </div>
    );
  }

  const { clip, match, owner, players } = clipData;

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      {/* Header */}
      <header className="bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Play size={28} weight="fill" className="text-[#007AFF]" />
            <span className="text-xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>SOCCER SCOUT</span>
          </div>
          <span className="text-xs text-[#666] bg-white/5 px-3 py-1.5 uppercase tracking-wider">
            Shared by {owner}
          </span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Video Player */}
        <div className="bg-black rounded-lg overflow-hidden mb-6">
          <video ref={videoRef} data-testid="shared-clip-video" controls autoPlay
            className="w-full aspect-video"
            src={`${API}/shared/clip/${shareToken}/video`}
            preload="auto" />
        </div>

        {/* Clip Info */}
        <div className="bg-[#141414] border border-white/10 p-6 rounded-lg mb-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>{clip.title}</h1>
              {match && (
                <div className="flex items-center gap-4 text-sm text-[#A3A3A3] mb-3">
                  <span className="flex items-center gap-1.5">
                    <Trophy size={16} className="text-[#007AFF]" />
                    {match.team_home} vs {match.team_away}
                  </span>
                  {match.competition && (
                    <span className="text-[#666]">{match.competition}</span>
                  )}
                  <span className="flex items-center gap-1">
                    <CalendarBlank size={14} />
                    {new Date(match.date + 'T00:00:00').toLocaleDateString()}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-3 text-xs text-[#666]">
                <span className="bg-white/5 px-2 py-1 uppercase">{clip.clip_type}</span>
                <span>{formatTime(clip.start_time)} — {formatTime(clip.end_time)}</span>
                <span>({Math.round(clip.end_time - clip.start_time)}s)</span>
              </div>
              {clip.description && (
                <p className="text-sm text-[#A3A3A3] mt-3">{clip.description}</p>
              )}
              {/* Tagged Players */}
              {players && players.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {players.map(p => (
                    <span key={p.id} className="flex items-center gap-1.5 bg-[#007AFF]/10 text-[#007AFF] text-xs px-2 py-1 rounded">
                      {p.profile_pic_url && (
                        <img src={`${API.replace('/api', '')}${p.profile_pic_url}`} alt="" className="w-4 h-4 rounded-full object-cover" />
                      )}
                      #{p.number ?? '?'} {p.name}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Share Buttons */}
            <div className="flex-shrink-0 relative">
              <button data-testid="share-clip-btn" onClick={handleNativeShare}
                className="flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-5 py-2.5 font-bold tracking-wider uppercase text-xs transition-colors">
                <ShareNetwork size={16} weight="bold" /> Share
              </button>

              {showShareMenu && (
                <div data-testid="share-menu" className="absolute right-0 top-full mt-2 bg-[#1F1F1F] border border-white/10 rounded-lg p-3 min-w-[220px] shadow-xl z-50">
                  <p className="text-[10px] text-[#666] uppercase tracking-wider mb-2">Share to</p>
                  {shareLinks.map(link => (
                    <a key={link.name} href={link.url} target="_blank" rel="noopener noreferrer"
                      data-testid={`share-${link.name.toLowerCase().replace(/\s/g, '-')}`}
                      className="flex items-center gap-3 px-3 py-2 rounded hover:bg-white/5 transition-colors"
                      onClick={(e) => { if (link.note) { e.preventDefault(); handleCopy(); } }}>
                      <div className="w-6 h-6 rounded flex items-center justify-center text-white text-[10px] font-bold"
                        style={{ backgroundColor: link.color }}>
                        {link.icon.toUpperCase().slice(0, 2)}
                      </div>
                      <span className="text-sm text-white">{link.name}</span>
                    </a>
                  ))}
                  <div className="border-t border-white/5 mt-2 pt-2">
                    <button data-testid="copy-clip-link-btn" onClick={handleCopy}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded transition-colors ${
                        copied ? 'bg-[#4ADE80]/10 text-[#4ADE80]' : 'hover:bg-white/5 text-white'
                      }`}>
                      {copied ? <Check size={16} /> : <Copy size={16} />}
                      <span className="text-sm">{copied ? 'Copied!' : 'Copy Link'}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      <footer className="border-t border-white/5 px-6 py-4 text-center">
        <p className="text-xs text-[#555]">
          Powered by <span className="text-[#007AFF]">Soccer Scout</span> — AI-Powered Match Analysis
        </p>
      </footer>
    </div>
  );
};

export default SharedClipView;
