/**
 * BuildInfoChip
 * --------------
 * Two-second deploy sanity check. Fetches `/api/health/deploy` on mount and
 * renders the current build label in the dashboard footer. Clicking expands
 * a small popover with the full shipped-feature list + git SHA — so after
 * each redeploy the user can confirm the latest code is live without
 * clicking through every feature.
 */
import { useState, useEffect } from 'react';
import axios from 'axios';
import { API } from '../App';
import { X, CheckCircle, GitBranch } from '@phosphor-icons/react';

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

  if (!info) return null;

  return (
    <>
      <button
        type="button"
        data-testid="build-info-chip"
        onClick={() => setOpen(true)}
        title={`Click for full build details — SHA ${info.sha}`}
        className="text-[10px] tracking-[0.2em] uppercase text-[#666] hover:text-[#007AFF] transition-colors cursor-pointer">
        v1.0 · <span className="text-[#A3A3A3] font-bold">{info.build}</span>
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
