/**
 * BuildInfoChip
 * --------------
 * Two-second deploy sanity check. Fetches `/api/health/deploy` on mount and
 * renders the current build label in the dashboard footer. Clicking expands
 * a small popover with the full shipped-feature list + git SHA — so after
 * each redeploy the user can confirm the latest code is live without
 * clicking through every feature.
 */
import { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { API } from '../App';
import { X, CheckCircle, GitBranch, Warning } from '@phosphor-icons/react';

const STALE_THRESHOLD_DAYS = 7;

const BuildInfoChip = () => {
  const [info, setInfo] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/health/deploy`)
      .then((res) => { if (!cancelled) setInfo(res.data); })
      .catch(() => { /* silent — chip just won't render if endpoint is unreachable */ });
    return () => { cancelled = true; };
  }, []);

  // Compare build time vs now → if older than threshold, surface a stale-build warning.
  const staleness = useMemo(() => {
    if (!info?.built_at) return { isStale: false, daysOld: 0 };
    const builtMs = new Date(info.built_at).getTime();
    if (Number.isNaN(builtMs)) return { isStale: false, daysOld: 0 };
    const daysOld = Math.floor((Date.now() - builtMs) / (1000 * 60 * 60 * 24));
    return { isStale: daysOld >= STALE_THRESHOLD_DAYS, daysOld };
  }, [info]);

  if (!info) return null;

  const chipColor = staleness.isStale
    ? 'text-[#FBBF24] hover:text-[#fcd34d]'
    : 'text-[#666] hover:text-[#007AFF]';

  return (
    <>
      <button
        type="button"
        data-testid="build-info-chip"
        data-stale={staleness.isStale ? 'true' : 'false'}
        onClick={() => setOpen(true)}
        title={staleness.isStale
          ? `Stale build (${staleness.daysOld} days old) — consider redeploying`
          : `Click for full build details — SHA ${info.sha}`}
        className={`text-[10px] tracking-[0.2em] uppercase transition-colors cursor-pointer inline-flex items-center gap-1.5 ${chipColor}`}>
        {staleness.isStale && <Warning size={11} weight="fill" className="text-[#FBBF24]" />}
        v1.0 · <span className={`font-bold ${staleness.isStale ? 'text-[#FBBF24]' : 'text-[#A3A3A3]'}`}>{info.build}</span>
      </button>

      {open && (
        <div
          data-testid="build-info-modal"
          className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4"
          onClick={() => setOpen(false)}
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>
          <div
            role="dialog"
            aria-label="Build info"
            className="bg-[#0F0F0F] border border-white/10 w-full sm:max-w-md max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-[#0F0F0F] border-b border-white/10 px-5 py-4 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold tracking-wider uppercase text-white" style={{ fontFamily: 'Bebas Neue' }}>
                  Build · {info.build}
                </h2>
                <p className="text-[10px] tracking-[0.15em] uppercase text-[#A3A3A3] mt-0.5 flex items-center gap-1.5">
                  <GitBranch size={11} weight="bold" />
                  SHA <span className="font-mono">{info.sha}</span>
                </p>
              </div>
              <button
                data-testid="close-build-info"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
                <X size={14} className="text-white" />
              </button>
            </div>

            <div className="p-5">
              {staleness.isStale && (
                <div
                  data-testid="build-staleness-warning"
                  className="mb-4 bg-[#FBBF24]/10 border border-[#FBBF24]/40 p-3 flex items-start gap-2">
                  <Warning size={16} weight="fill" className="text-[#FBBF24] flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-bold text-white">
                      Stale build · {staleness.daysOld} days old
                    </p>
                    <p className="text-[11px] text-[#CFCFCF] mt-0.5 leading-snug">
                      Preview likely has newer code. Save to GitHub + redeploy to ship the latest features.
                    </p>
                  </div>
                </div>
              )}

              <p className="text-xs text-[#A3A3A3] mb-3">
                Built <span className="text-white">{new Date(info.built_at).toLocaleString()}</span>
                {' · '}
                <span className="text-[#10B981] font-bold">{info.feature_count}</span> features shipped.
              </p>
              <ul className="space-y-1.5" data-testid="build-feature-list">
                {info.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-xs text-[#CFCFCF]">
                    <CheckCircle size={12} weight="fill" className="text-[#10B981] flex-shrink-0" />
                    <span className="font-mono">{f}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default BuildInfoChip;
