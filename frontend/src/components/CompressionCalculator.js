/**
 * CompressionCalculator
 * ----------------------
 * Plug in a raw video size (auto-detected from a selected file, or manually entered)
 * and a typical network upload speed → see projected HandBrake output sizes + upload
 * times for the four most useful presets. Demystifies "is this setting too aggressive?"
 * for non-technical coaches.
 *
 * Ratios are approximate, calibrated against typical sideline-cam capture (~15-25 Mbps
 * source). Actual results can vary ±20% depending on motion, lighting, and source
 * bitrate. The component is upfront about this in the footnote.
 */
import { useState, useMemo } from 'react';
import { Lightning, Star, Speedometer } from '@phosphor-icons/react';

const PRESETS = [
  {
    id: 'fast-720p30',
    label: 'Fast 720p30',
    cq: 'CQ 22',
    ratio: 0.18,
    badge: 'Smallest',
    badgeColor: 'text-[#10B981] border-[#10B981]/40 bg-[#10B981]/10',
    note: '720p source — AI quality identical (server downscales to 240p anyway).',
  },
  {
    id: 'fast-1080p30',
    label: 'Fast 1080p30',
    cq: 'CQ 22',
    ratio: 0.35,
    badge: 'Recommended',
    badgeColor: 'text-[#FBBF24] border-[#FBBF24]/40 bg-[#FBBF24]/10',
    note: 'Keeps 1080p for your own playback. Best balance of size & visual quality.',
  },
  {
    id: 'fast-1080p30-cq25',
    label: 'Fast 1080p30',
    cq: 'CQ 25',
    ratio: 0.22,
    badge: 'Aggressive',
    badgeColor: 'text-[#A3A3A3] border-white/15 bg-white/5',
    note: 'Visible artifacts on close zoom-ins. AI analysis unaffected.',
  },
  {
    id: 'fast-1080p60',
    label: 'Fast 1080p60',
    cq: 'CQ 22',
    ratio: 0.55,
    badge: 'Slow-mo ready',
    badgeColor: 'text-[#007AFF] border-[#007AFF]/40 bg-[#007AFF]/10',
    note: 'Only worth the extra size if you want 60 fps slow-mo replays.',
  },
];

const NETWORK_SPEEDS = [
  { id: '10', label: '10 Mbps · DSL', mbps: 10 },
  { id: '25', label: '25 Mbps · cable', mbps: 25 },
  { id: '50', label: '50 Mbps · fiber', mbps: 50 },
  { id: '100', label: '100 Mbps · gigabit', mbps: 100 },
];

const _formatGB = (bytes) => {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
};

const _formatUpload = (bytes, mbps) => {
  // mbps in megabits, bytes need to convert: bits = bytes * 8, seconds = bits / (mbps * 1_000_000)
  const seconds = (bytes * 8) / (mbps * 1_000_000);
  const mins = seconds / 60;
  if (mins < 1) return '<1 min';
  if (mins < 60) return `${Math.round(mins)} min`;
  const hrs = mins / 60;
  return `${hrs.toFixed(hrs < 10 ? 1 : 0)} hr`;
};

const CompressionCalculator = ({ initialSizeBytes = 0 }) => {
  // User-editable raw file size in GB
  const [sizeGB, setSizeGB] = useState(() => {
    if (initialSizeBytes > 0) return (initialSizeBytes / 1024 ** 3).toFixed(1);
    return '12';
  });
  const [networkId, setNetworkId] = useState('25');

  const rawBytes = useMemo(() => {
    const n = parseFloat(sizeGB);
    if (Number.isNaN(n) || n <= 0) return 0;
    return Math.min(n, 50) * 1024 ** 3; // clamp to 50 GB so the math stays sensible
  }, [sizeGB]);

  const mbps = useMemo(
    () => NETWORK_SPEEDS.find((n) => n.id === networkId)?.mbps ?? 25,
    [networkId]
  );

  const rawUploadTime = rawBytes > 0 ? _formatUpload(rawBytes, mbps) : '—';

  return (
    <div
      data-testid="compression-calculator"
      className="mt-4 pt-4 border-t border-[#FBBF24]/15">
      <div className="flex items-center gap-2 mb-3">
        <Speedometer size={14} weight="bold" className="text-[#FBBF24]" />
        <p className="text-[10px] tracking-[0.15em] uppercase text-[#FBBF24] font-bold">
          Estimate your savings
        </p>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <label className="block">
          <span className="block text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-1">
            Raw file size
          </span>
          <div className="relative">
            <input
              data-testid="calc-size-input"
              type="number"
              inputMode="decimal"
              step="0.5"
              min="0.5"
              max="50"
              value={sizeGB}
              onChange={(e) => setSizeGB(e.target.value)}
              className="w-full bg-[#0A0A0A] border border-white/10 px-3 py-2 pr-10 text-sm text-white font-mono focus:outline-none focus:border-[#FBBF24]/60"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[#666] pointer-events-none">
              GB
            </span>
          </div>
        </label>

        <label className="block">
          <span className="block text-[10px] tracking-wider uppercase text-[#A3A3A3] mb-1">
            Upload speed
          </span>
          <select
            data-testid="calc-network-select"
            value={networkId}
            onChange={(e) => setNetworkId(e.target.value)}
            className="w-full bg-[#0A0A0A] border border-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:border-[#FBBF24]/60">
            {NETWORK_SPEEDS.map((n) => (
              <option key={n.id} value={n.id}>{n.label}</option>
            ))}
          </select>
        </label>
      </div>

      {/* Baseline: upload as-is */}
      <div
        data-testid="calc-baseline-row"
        className="flex items-center justify-between gap-2 px-3 py-2 mb-3 bg-white/[0.02] border border-white/10">
        <div>
          <p className="text-[10px] tracking-[0.15em] uppercase text-[#A3A3A3] font-bold mb-0.5">
            Upload as-is
          </p>
          <p className="text-xs text-white">
            {_formatGB(rawBytes)} · <span className="text-[#EF4444]">~{rawUploadTime}</span> at {mbps} Mbps
          </p>
        </div>
        <Lightning size={18} weight="fill" className="text-[#666] flex-shrink-0" />
      </div>

      {/* Preset projections */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {PRESETS.map((p) => {
          const projected = rawBytes * p.ratio;
          const upload = projected > 0 ? _formatUpload(projected, mbps) : '—';
          const savings = rawBytes > 0
            ? Math.round((1 - p.ratio) * 100)
            : 0;
          return (
            <div
              key={p.id}
              data-testid={`calc-preset-${p.id}`}
              className="bg-[#0A0A0A] border border-white/10 p-3">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <p className="text-xs font-bold text-white leading-tight">
                  {p.label}
                  <span className="text-[#666] font-normal ml-1">· {p.cq}</span>
                </p>
                <span className={`text-[9px] tracking-wider uppercase font-bold border px-1.5 py-0.5 flex-shrink-0 ${p.badgeColor}`}>
                  {p.badge === 'Recommended' && <Star size={9} weight="fill" className="inline-block mr-0.5 -translate-y-[1px]" />}
                  {p.badge}
                </span>
              </div>
              <p className="text-base font-bold text-white leading-none" data-testid={`calc-preset-${p.id}-size`}>
                {_formatGB(projected)}
                <span className="text-xs text-[#10B981] font-normal ml-2">−{savings}%</span>
              </p>
              <p className="text-[11px] text-[#A3A3A3] mt-1" data-testid={`calc-preset-${p.id}-time`}>
                ~{upload} upload
              </p>
              <p className="text-[10px] text-[#666] mt-1.5 leading-snug">
                {p.note}
              </p>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-[#666] mt-3 italic leading-snug">
        Estimates based on typical sideline-cam source (~15-25 Mbps). Actual output can vary ±20% depending on motion & lighting.
      </p>
    </div>
  );
};

export default CompressionCalculator;
