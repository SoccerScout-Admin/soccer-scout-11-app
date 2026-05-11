import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import {
  FilmReel, MagnifyingGlass, CalendarBlank, PlayCircle, ArrowLeft, Flame, Eye,
} from '@phosphor-icons/react';

const formatDuration = (seconds) => {
  if (!seconds || seconds <= 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`;
};

const ReelTile = ({ reel, compact = false, showTrendingBadge = false }) => {
  const ogImage = `${API}/og/highlight-reel/${reel.share_token}/image.png`;
  const hasScore = reel.home_score !== undefined && reel.home_score !== null;
  return (
    <Link
      to={`/reel/${reel.share_token}`}
      data-testid={`browse-reel-${reel.share_token}`}
      className={`group block bg-[#141414] border border-white/10 hover:border-[#007AFF]/40 overflow-hidden transition-colors ${compact ? 'w-72 flex-shrink-0' : ''}`}>
      <div className="relative aspect-[1200/630] bg-[#0A0A0A] overflow-hidden">
        <img
          src={ogImage}
          alt={`${reel.team_home} vs ${reel.team_away} highlights`}
          loading="lazy"
          className="w-full h-full object-cover group-hover:scale-[1.02] transition-transform duration-500"
          onError={(e) => { e.currentTarget.style.opacity = '0.3'; }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent pointer-events-none" />
        {showTrendingBadge && (
          <span className="absolute top-3 left-3 inline-flex items-center gap-1 text-[10px] tracking-[0.2em] uppercase font-bold bg-[#EF4444] text-white px-2 py-0.5">
            <Flame size={11} weight="fill" /> Trending
          </span>
        )}
        <div className="absolute top-3 right-3 flex flex-col gap-1 items-end">
          <span className="text-[10px] tracking-[0.2em] uppercase font-bold bg-[#007AFF] text-black px-2 py-0.5">
            {reel.total_clips} clips
          </span>
          <span className="text-[10px] tracking-[0.2em] uppercase font-bold bg-[#10B981] text-black px-2 py-0.5">
            {formatDuration(reel.duration_seconds)}
          </span>
        </div>
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <PlayCircle size={56} weight="fill" className="text-white drop-shadow-2xl" />
        </div>
      </div>
      <div className="p-4">
        <div className="flex items-baseline justify-between gap-2 mb-1.5">
          <h3 className="text-base font-bold text-white truncate" style={{ fontFamily: 'Bebas Neue' }}>
            {reel.team_home} vs {reel.team_away}
          </h3>
          {hasScore && (
            <span className="text-sm font-bold text-[#007AFF] tabular-nums whitespace-nowrap" style={{ fontFamily: 'Bebas Neue' }}>
              {reel.home_score}–{reel.away_score}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] tracking-wider text-[#A3A3A3] truncate">
          {reel.competition && <span className="truncate">{reel.competition}</span>}
          {reel.coach_name && <span className="truncate">· Coach {reel.coach_name}</span>}
        </div>
        <div className="flex items-center gap-3 mt-1 text-[10px] text-[#666]">
          {reel.date && (
            <span className="flex items-center gap-1">
              <CalendarBlank size={11} /> {new Date(reel.date + 'T00:00:00').toLocaleDateString()}
            </span>
          )}
          {(reel.view_count ?? 0) > 0 && (
            <span className="flex items-center gap-1">
              <Eye size={11} /> {reel.view_count}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
};

const TrendingStrip = ({ reels }) => {
  if (!reels.length) return null;
  return (
    <section data-testid="trending-strip" className="mb-8">
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <div className="flex items-center gap-2">
          <Flame size={18} weight="fill" className="text-[#EF4444]" />
          <h2 className="text-xl sm:text-2xl font-bold uppercase tracking-wider text-white" style={{ fontFamily: 'Bebas Neue' }}>
            Trending This Week
          </h2>
        </div>
        <span className="text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3]">
          Last 7 days · By views
        </span>
      </div>
      <div className="flex gap-4 overflow-x-auto pb-3 -mx-4 px-4 sm:mx-0 sm:px-0 snap-x snap-mandatory" data-testid="trending-scroll">
        {reels.map((r) => (
          <div key={`trending-${r.id}`} className="snap-start">
            <ReelTile reel={r} compact showTrendingBadge />
          </div>
        ))}
      </div>
    </section>
  );
};

const HighlightReelsBrowse = () => {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const initialQ = params.get('q') || '';
  const initialComp = params.get('comp') || '';

  const [q, setQ] = useState(initialQ);
  const [competition, setCompetition] = useState(initialComp);
  const [reels, setReels] = useState([]);
  const [trending, setTrending] = useState([]);
  const [competitions, setCompetitions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchReels = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/highlight-reels/browse`, {
        params: { q, competition, limit: 48 },
      });
      setReels(res.data.reels || []);
    } catch (err) {
      console.warn('Failed to fetch browse reels:', err);
      setReels([]);
    } finally {
      setLoading(false);
    }
  }, [q, competition]);

  // Trending is fetched once on mount — independent of filters so users
  // always see what's hot regardless of what they've searched for.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      axios.get(`${API}/highlight-reels/browse/competitions`).then((r) => r.data.competitions || []).catch(() => []),
      axios.get(`${API}/highlight-reels/trending`, { params: { limit: 12 } }).then((r) => r.data.reels || []).catch(() => []),
    ]).then(([comps, trnd]) => {
      if (cancelled) return;
      setCompetitions(comps);
      setTrending(trnd);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const id = setTimeout(fetchReels, 250);  // debounce typing
    return () => clearTimeout(id);
  }, [fetchReels]);

  // Sync URL with filters so the page is shareable
  useEffect(() => {
    const next = new URLSearchParams();
    if (q) next.set('q', q);
    if (competition) next.set('comp', competition);
    setParams(next, { replace: true });
  }, [q, competition, setParams]);

  const competitionChips = useMemo(() => ['', ...competitions], [competitions]);
  const hasActiveFilters = q || competition;

  return (
    <div className="min-h-screen bg-[#0A0A0A]" data-testid="reels-browse-page">
      <header className="sticky top-0 z-40 bg-[#0A0A0A]/95 backdrop-blur border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center gap-3">
          <button
            data-testid="reels-browse-back"
            onClick={() => navigate(-1)}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={20} className="text-white" />
          </button>
          <div className="flex items-center gap-2">
            <FilmReel size={20} weight="fill" className="text-[#007AFF]" />
            <h1 className="text-2xl sm:text-3xl font-bold text-white uppercase tracking-wider" style={{ fontFamily: 'Bebas Neue' }}>
              Reel Library
            </h1>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        <div className="mb-6">
          <p className="text-sm text-[#A3A3A3] mb-4 max-w-2xl">
            Public highlight reels shared by coaches across the platform.
            Click any reel to watch it — no sign-in required.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <div className="relative flex-1">
              <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
              <input
                data-testid="reels-search-input"
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search teams, coaches…"
                className="w-full bg-[#141414] border border-white/10 text-white pl-10 pr-3 py-2.5 text-sm focus:border-[#007AFF] focus:outline-none"
              />
            </div>
          </div>
          {competitionChips.length > 1 && (
            <div className="flex flex-wrap gap-2 mb-2" data-testid="competition-chips">
              {competitionChips.map((c) => (
                <button
                  key={c || 'all'}
                  data-testid={`comp-chip-${c || 'all'}`}
                  onClick={() => setCompetition(c)}
                  className={`px-3 py-1.5 text-[10px] font-bold tracking-wider uppercase transition-colors ${
                    competition === c
                      ? 'bg-[#007AFF] text-white'
                      : 'border border-white/10 text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
                  }`}>
                  {c || 'All Competitions'}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Trending strip — hidden while filtering so it doesn't compete for attention */}
        {!hasActiveFilters && <TrendingStrip reels={trending} />}

        {!hasActiveFilters && reels.length > 0 && (
          <h2 className="text-xl font-bold uppercase tracking-wider text-white mb-3" style={{ fontFamily: 'Bebas Neue' }}>
            All Reels
          </h2>
        )}

        {loading ? (
          <div className="text-center py-16" data-testid="reels-loading">
            <div className="w-6 h-6 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin mx-auto" />
          </div>
        ) : reels.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-white/10" data-testid="reels-empty">
            <FilmReel size={48} className="text-[#333] mx-auto mb-3" />
            <p className="text-base text-white mb-1" style={{ fontFamily: 'Bebas Neue' }}>
              No public reels match your filters yet
            </p>
            <p className="text-xs text-[#A3A3A3]">
              {hasActiveFilters ? 'Try clearing the search/filter.' : 'Coaches haven\'t shared any reels yet — be the first!'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-5" data-testid="reels-grid">
            {reels.map((r) => <ReelTile key={r.id} reel={r} />)}
          </div>
        )}

        <p className="mt-12 text-center text-[10px] tracking-[0.2em] uppercase text-[#666]">
          Powered by Soccer Scout 11 · AI-Curated Highlight Reels
        </p>
      </main>
    </div>
  );
};

export default HighlightReelsBrowse;
