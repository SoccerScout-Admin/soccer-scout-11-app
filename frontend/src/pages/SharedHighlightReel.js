import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { FilmReel, CalendarBlank } from '@phosphor-icons/react';

const SharedHighlightReel = () => {
  const { shareToken } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/highlight-reels/public/${shareToken}`)
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch((err) => {
        if (!cancelled) {
          setError(err.response?.status === 404 ? 'Reel not available' : 'Failed to load');
        }
      });
    return () => { cancelled = true; };
  }, [shareToken]);

  if (error) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center px-6">
        <div className="text-center" data-testid="reel-error">
          <p className="text-2xl text-white mb-2" style={{ fontFamily: 'Bebas Neue' }}>{error}</p>
          <p className="text-sm text-[#A3A3A3]">The coach may have revoked this share link.</p>
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

  const videoUrl = `${API}/highlight-reels/public/${shareToken}/video`;
  const durMin = Math.floor((data.duration_seconds || 0) / 60);
  const durSec = Math.round((data.duration_seconds || 0) % 60);
  const durLabel = durMin > 0 ? `${durMin}:${String(durSec).padStart(2, '0')}` : `${durSec}s`;

  return (
    <div className="min-h-screen bg-[#0A0A0A]" data-testid="shared-reel-page">
      <header className="border-b border-white/10 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <img src="/logo-mark-96.png" alt="Soccer Scout 11" className="h-8 w-auto" />
          <span className="text-xs tracking-[0.2em] uppercase text-[#A3A3A3] font-bold">Match Highlights</span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-6">
        <div className="bg-gradient-to-br from-[#0F1A2E] to-[#141414] border-l-4 border-[#007AFF] p-6 sm:p-8">
          <div className="flex items-center gap-2 mb-3">
            <FilmReel size={14} weight="fill" className="text-[#007AFF]" />
            <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#007AFF]">
              {data.competition || 'Match Highlights'}
            </span>
          </div>
          <h1 className="text-3xl sm:text-5xl font-bold text-white mb-4 leading-tight" style={{ fontFamily: 'Bebas Neue' }}>
            {data.team_home} vs {data.team_away}
          </h1>
          <div className="flex items-baseline gap-4 flex-wrap mb-3">
            {data.home_score !== undefined && data.away_score !== undefined && (
              <span className="text-5xl sm:text-6xl font-bold text-white tabular-nums" style={{ fontFamily: 'Bebas Neue' }}>
                {data.home_score} – {data.away_score}
              </span>
            )}
            <div className="flex flex-wrap gap-2">
              <span className="text-xs font-bold tracking-[0.2em] uppercase px-3 py-1.5 bg-[#007AFF] text-black">
                {data.total_clips} Clips
              </span>
              <span className="text-xs font-bold tracking-[0.2em] uppercase px-3 py-1.5 bg-[#10B981] text-black">
                {durLabel} Reel
              </span>
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs text-[#A3A3A3] flex-wrap">
            {data.date && (
              <span className="flex items-center gap-1.5">
                <CalendarBlank size={14} /> {new Date(data.date + 'T00:00:00').toLocaleDateString()}
              </span>
            )}
            {data.coach_name && <span>· Coach {data.coach_name}</span>}
          </div>
        </div>

        <div className="bg-black border border-white/10 overflow-hidden">
          <video
            data-testid="shared-reel-video"
            controls
            autoPlay
            playsInline
            preload="metadata"
            className="w-full h-auto block bg-black"
            src={videoUrl}
          >
            <track kind="captions" />
            Your browser does not support video playback.
          </video>
        </div>

        <div className="text-center text-[10px] tracking-[0.2em] uppercase text-[#666] pt-4">
          Powered by Soccer Scout 11 · AI-Curated Highlight Reel
        </div>
      </main>
    </div>
  );
};

export default SharedHighlightReel;
