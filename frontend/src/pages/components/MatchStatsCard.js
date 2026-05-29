import { useMemo } from 'react';
import { ChartBar, Path } from '@phosphor-icons/react';

/**
 * iter107 — Veo-style match-stats card.
 *
 * Renders only if a `possession_stats` analysis row exists with content.
 * Parses the Gemini JSON response and surfaces:
 *   - Side-by-side possession % bar (home vs away, color-coded by jersey)
 *   - Longest pass string per team (highlighted number callout)
 *   - Total passes estimate per team
 *   - One-line tactical summary
 *
 * Placed above the video player on VideoAnalysis so coaches see the
 * shape of the match before diving into individual moments.
 */

const _parseJsonContent = (raw) => {
  if (!raw) return null;
  if (typeof raw === 'object') return raw;
  // Gemini sometimes wraps the JSON in ```json fences — strip them
  const stripped = String(raw).trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/```\s*$/, '');
  try { return JSON.parse(stripped); } catch { /* fall through */ }
  // Try to extract the first {...} balanced block
  const m = stripped.match(/\{[\s\S]*\}/);
  if (m) {
    try { return JSON.parse(m[0]); } catch { return null; }
  }
  return null;
};

const PassStringCard = ({ team, count, accent, testid }) => (
  <div
    data-testid={testid}
    className="flex-1 bg-[#0A0A0A] border border-white/5 p-4 text-center"
  >
    <p className="text-[10px] tracking-[0.2em] uppercase text-[#666] mb-2">Longest pass string</p>
    <p
      className="text-3xl font-bold tabular-nums leading-none mb-1"
      style={{ fontFamily: 'Space Grotesk', color: accent }}
    >
      {count}
    </p>
    <p className="text-[11px] text-[#A3A3A3] truncate">{team}</p>
  </div>
);

const MatchStatsCard = ({ analyses, match }) => {
  const possessionAnalysis = useMemo(
    () => (analyses || []).find((a) => a.analysis_type === 'possession_stats' && a.status === 'completed'),
    [analyses],
  );

  const stats = useMemo(
    () => _parseJsonContent(possessionAnalysis?.content),
    [possessionAnalysis],
  );

  if (!stats || !possessionAnalysis) return null;

  // Clamp + normalize so the bar always sums to 100
  let homePct = Math.max(0, Math.min(100, Number(stats.team_home_possession_pct) || 0));
  let awayPct = Math.max(0, Math.min(100, Number(stats.team_away_possession_pct) || 0));
  if (homePct + awayPct === 0) { homePct = 50; awayPct = 50; }
  if (homePct + awayPct !== 100) {
    const total = homePct + awayPct;
    homePct = Math.round((homePct / total) * 100);
    awayPct = 100 - homePct;
  }

  const homeName = match?.team_home || 'Home';
  const awayName = match?.team_away || 'Away';
  // Use jersey colors for the bar if provided, otherwise default sky/red
  const homeAccent = match?.team_home_jersey_color
    ? _kitColorToHex(match.team_home_jersey_color) : '#0EA5E9';
  const awayAccent = match?.team_away_jersey_color
    ? _kitColorToHex(match.team_away_jersey_color) : '#EF4444';

  const homeLongest = stats.team_home_longest_pass_string ?? '—';
  const awayLongest = stats.team_away_longest_pass_string ?? '—';
  const homeTotal = stats.team_home_total_passes_estimate;
  const awayTotal = stats.team_away_total_passes_estimate;
  const summary = stats.summary;

  return (
    <section
      data-testid="match-stats-card"
      className="bg-[#141414] border border-white/10 mb-6"
    >
      <header className="flex items-center gap-2 px-5 py-3 border-b border-white/10">
        <ChartBar size={16} weight="bold" className="text-[#FBBF24]" />
        <h2 className="text-xs font-bold tracking-[0.2em] uppercase text-[#E5E5E5]">
          Match Stats
        </h2>
        <span className="ml-auto text-[10px] text-[#666] tracking-wider uppercase">AI estimate</span>
      </header>

      {/* Possession split */}
      <div className="px-5 pt-5 pb-3">
        <div className="flex items-end justify-between mb-2 text-xs">
          <div data-testid="possession-home" className="flex items-center gap-2 min-w-0">
            <span className="w-2.5 h-2.5 flex-shrink-0" style={{ backgroundColor: homeAccent }} />
            <span className="text-[#E5E5E5] truncate">{homeName}</span>
            <span className="text-white font-bold tabular-nums" style={{ fontFamily: 'Space Grotesk' }}>
              {homePct}%
            </span>
          </div>
          <div data-testid="possession-away" className="flex items-center gap-2 min-w-0 text-right">
            <span className="text-white font-bold tabular-nums" style={{ fontFamily: 'Space Grotesk' }}>
              {awayPct}%
            </span>
            <span className="text-[#E5E5E5] truncate">{awayName}</span>
            <span className="w-2.5 h-2.5 flex-shrink-0" style={{ backgroundColor: awayAccent }} />
          </div>
        </div>
        <p className="text-[10px] tracking-[0.2em] uppercase text-[#666] mb-2">Possession</p>
        <div className="h-3 w-full bg-[#0A0A0A] border border-white/5 flex overflow-hidden">
          <div
            data-testid="possession-bar-home"
            className="h-full transition-all duration-700"
            style={{ width: `${homePct}%`, backgroundColor: homeAccent }}
          />
          <div
            data-testid="possession-bar-away"
            className="h-full transition-all duration-700"
            style={{ width: `${awayPct}%`, backgroundColor: awayAccent }}
          />
        </div>
      </div>

      {/* Pass strings */}
      <div className="px-5 py-4 grid grid-cols-2 gap-3">
        <PassStringCard
          team={homeName}
          count={homeLongest}
          accent={homeAccent}
          testid="pass-string-home"
        />
        <PassStringCard
          team={awayName}
          count={awayLongest}
          accent={awayAccent}
          testid="pass-string-away"
        />
      </div>

      {/* Total passes (secondary) */}
      {(homeTotal !== undefined || awayTotal !== undefined) && (
        <div className="px-5 pb-4 flex items-center justify-between text-[11px] text-[#A3A3A3]">
          <div className="flex items-center gap-2">
            <Path size={12} weight="bold" style={{ color: homeAccent }} />
            <span>~<span className="tabular-nums text-white font-semibold">{homeTotal ?? '—'}</span> total passes</span>
          </div>
          <span className="text-[#444]">·</span>
          <div className="flex items-center gap-2">
            <span>~<span className="tabular-nums text-white font-semibold">{awayTotal ?? '—'}</span> total passes</span>
            <Path size={12} weight="bold" style={{ color: awayAccent }} />
          </div>
        </div>
      )}

      {/* Tactical summary */}
      {summary && (
        <p
          data-testid="match-stats-summary"
          className="px-5 pb-5 text-[12px] text-[#A3A3A3] italic leading-relaxed border-t border-white/5 pt-4"
        >
          “{summary}”
        </p>
      )}
    </section>
  );
};

// Common kit colors → hex. Falls through to gray when the user typed
// something unrecognized.
const _KIT_COLOR_MAP = {
  red: '#EF4444',
  blue: '#3B82F6',
  navy: '#1E3A8A',
  green: '#10B981',
  yellow: '#FBBF24',
  gold: '#F59E0B',
  orange: '#F97316',
  black: '#171717',
  white: '#F5F5F5',
  gray: '#9CA3AF',
  grey: '#9CA3AF',
  purple: '#A855F7',
  pink: '#EC4899',
  maroon: '#7F1D1D',
  teal: '#14B8A6',
  cyan: '#22D3EE',
  brown: '#92400E',
  silver: '#D1D5DB',
};

function _kitColorToHex(name) {
  if (!name) return '#888';
  const trimmed = String(name).trim().toLowerCase();
  // Already a hex
  if (/^#[0-9a-f]{3,8}$/i.test(trimmed)) return trimmed;
  return _KIT_COLOR_MAP[trimmed] || '#888';
}

export default MatchStatsCard;
