/**
 * Compact stats card for the coach's own highlight reels.
 *
 * Renders nothing when the user has no reels yet (avoids dead zone).
 * When data exists, shows: total reels / total views / 7d views + a hero
 * "Most-Viewed This Week" tile that deep-links to the public reel page.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { FilmReel, Eye, Flame, ArrowUpRight, ShareNetwork } from '@phosphor-icons/react';

const formatDuration = (s) => {
  if (!s || s <= 0) return '—';
  const m = Math.floor(s / 60);
  const ss = Math.round(s % 60);
  return m > 0 ? `${m}:${String(ss).padStart(2, '0')}` : `${ss}s`;
};

const MyReelStatsCard = () => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/highlight-reels/my-stats`, { headers: getAuthHeader() })
      .then((res) => { if (!cancelled) setStats(res.data); })
      .catch(() => { if (!cancelled) setStats(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) return null;
  // No reels — render nothing rather than a confusing "0 views" panel
  if (!stats || stats.total_reels === 0) return null;

  const { total_reels, shared_reels, views_7d, views_all_time, top_reel } = stats;

  return (
    <section data-testid="my-reel-stats" className="mb-6 bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-[#007AFF]/30 p-5 sm:p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <FilmReel size={18} weight="fill" className="text-[#007AFF]" />
          <h3 className="text-xl sm:text-2xl font-bold tracking-wider uppercase text-white" style={{ fontFamily: 'Bebas Neue' }}>
            My Reel Stats
          </h3>
        </div>
        <Link
          to="/reels"
          data-testid="visit-reel-library"
          className="hidden sm:inline-flex items-center gap-1 text-[10px] tracking-[0.2em] uppercase font-bold text-[#007AFF] hover:text-white transition-colors">
          Reel Library <ArrowUpRight size={11} weight="bold" />
        </Link>
      </div>

      <div className="grid grid-cols-3 gap-3 sm:gap-4 mb-4">
        <div className="bg-[#0A0A0A] border border-white/10 p-3 sm:p-4">
          <div className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A3A3A3] mb-1">Reels</div>
          <div className="text-3xl sm:text-4xl font-bold text-white tabular-nums" style={{ fontFamily: 'Bebas Neue' }}>
            {total_reels}
          </div>
          <div className="text-[10px] text-[#666] mt-1">
            <ShareNetwork size={10} className="inline mr-0.5" />
            {shared_reels} shared
          </div>
        </div>
        <div className="bg-[#0A0A0A] border border-white/10 p-3 sm:p-4">
          <div className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A3A3A3] mb-1">Views 7d</div>
          <div className="text-3xl sm:text-4xl font-bold text-[#10B981] tabular-nums" style={{ fontFamily: 'Bebas Neue' }}>
            {views_7d}
          </div>
          <div className="text-[10px] text-[#666] mt-1">
            <Eye size={10} className="inline mr-0.5" />
            last 7 days
          </div>
        </div>
        <div className="bg-[#0A0A0A] border border-white/10 p-3 sm:p-4">
          <div className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A3A3A3] mb-1">All-Time</div>
          <div className="text-3xl sm:text-4xl font-bold text-[#FBBF24] tabular-nums" style={{ fontFamily: 'Bebas Neue' }}>
            {views_all_time}
          </div>
          <div className="text-[10px] text-[#666] mt-1">
            <Eye size={10} className="inline mr-0.5" />
            total views
          </div>
        </div>
      </div>

      {top_reel ? (
        <Link
          to={`/reel/${top_reel.share_token}`}
          data-testid="top-reel-card"
          className="group flex items-center gap-3 sm:gap-4 bg-gradient-to-r from-[#EF4444]/10 to-transparent border border-[#EF4444]/30 hover:border-[#EF4444] p-3 sm:p-4 transition-colors">
          <div className="flex-shrink-0 w-12 h-12 sm:w-14 sm:h-14 bg-[#EF4444]/20 border border-[#EF4444]/40 flex items-center justify-center">
            <Flame size={24} weight="fill" className="text-[#EF4444]" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#EF4444]">
                Most-Viewed This Week
              </span>
            </div>
            <div className="text-base sm:text-lg font-bold text-white truncate" style={{ fontFamily: 'Bebas Neue' }}>
              {top_reel.team_home} vs {top_reel.team_away}
            </div>
            <div className="flex items-center gap-3 text-[10px] text-[#A3A3A3] mt-0.5">
              <span className="flex items-center gap-1 text-[#EF4444] font-bold">
                <Eye size={11} weight="bold" /> {top_reel.view_count}
              </span>
              <span>{top_reel.total_clips} clips</span>
              <span>{formatDuration(top_reel.duration_seconds)}</span>
            </div>
          </div>
          <ArrowUpRight size={20} weight="bold" className="text-[#A3A3A3] group-hover:text-white transition-colors flex-shrink-0" />
        </Link>
      ) : (
        <div data-testid="no-top-reel" className="text-center py-4 border border-dashed border-white/10">
          <p className="text-xs text-[#A3A3A3]">
            Share a reel to start tracking views & climb the trending board.
          </p>
        </div>
      )}
    </section>
  );
};

export default MyReelStatsCard;
