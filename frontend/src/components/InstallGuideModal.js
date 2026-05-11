/**
 * Install Guide modal — shown when a user clicks "Install on another device"
 * from the dashboard. Renders all install paths side-by-side with a QR code
 * so a coach can scan it from their phone (or pass it to an assistant coach).
 *
 * This is the static, tabbed cousin of `PWAInstallPrompt`. The prompt fires
 * automatically once per browser; this modal is on-demand and always shows
 * every platform.
 */
import { useMemo, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import {
  X, AppleLogo, AndroidLogo, Desktop, Share, Plus,
  DotsThree, DotsThreeVertical, GoogleChromeLogo,
} from '@phosphor-icons/react';

const PLATFORMS = [
  { key: 'ios', label: 'iPhone / iPad', Icon: AppleLogo, color: '#A3A3A3' },
  { key: 'android', label: 'Android', Icon: AndroidLogo, color: '#10B981' },
  { key: 'desktop', label: 'Desktop', Icon: Desktop, color: '#007AFF' },
];

const InstallGuideModal = ({ onClose }) => {
  const [active, setActive] = useState('ios');

  const installUrl = useMemo(() => {
    if (typeof window === 'undefined') return '';
    return `${window.location.origin}/`;
  }, []);

  return (
    <div
      data-testid="install-guide-modal"
      className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4"
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <div
        role="dialog"
        aria-label="Install guide"
        className="bg-[#0F0F0F] border border-white/10 w-full sm:max-w-2xl max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-[#0F0F0F] border-b border-white/10 px-5 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold tracking-wider uppercase text-white" style={{ fontFamily: 'Bebas Neue' }}>
              Install on Another Device
            </h2>
            <p className="text-xs text-[#A3A3A3] mt-0.5">
              Scan the QR code on your other device and follow the steps below.
            </p>
          </div>
          <button data-testid="close-install-guide" onClick={onClose}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10"
            aria-label="Close">
            <X size={18} className="text-white" />
          </button>
        </div>

        <div className="p-5 grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-5 sm:gap-6">
          {/* QR */}
          <div className="flex flex-col items-center sm:items-start">
            <div className="bg-white p-3 inline-block">
              <QRCodeSVG value={installUrl} size={144} bgColor="#ffffff" fgColor="#0A0A0A" level="M" />
            </div>
            <p className="mt-3 text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3] text-center sm:text-left">
              Scan from another device
            </p>
            <p className="text-[10px] text-[#666] mt-1 break-all text-center sm:text-left">{installUrl}</p>
          </div>

          {/* Tabbed instructions */}
          <div>
            <div className="flex gap-1 mb-4 border-b border-white/10">
              {PLATFORMS.map((p) => {
                const Icon = p.Icon;
                const isActive = active === p.key;
                return (
                  <button
                    key={p.key}
                    data-testid={`install-tab-${p.key}`}
                    onClick={() => setActive(p.key)}
                    className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-bold tracking-wider uppercase transition-colors border-b-2 -mb-px ${
                      isActive ? 'text-white border-[#007AFF]' : 'text-[#666] border-transparent hover:text-white'
                    }`}>
                    <Icon size={14} weight="bold" style={{ color: isActive ? p.color : undefined }} />
                    <span className="hidden sm:inline">{p.label}</span>
                  </button>
                );
              })}
            </div>

            {active === 'ios' && (
              <div data-testid="install-pane-ios">
                <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-3">iPhone / iPad — Safari</h3>
                <ol className="text-sm text-[#CFCFCF] leading-relaxed space-y-2 list-decimal list-inside marker:text-[#007AFF] marker:font-bold">
                  <li>Open Soccer Scout 11 in <strong className="text-white">Safari</strong> (Chrome / DuckDuckGo on iOS cannot install).</li>
                  <li>Tap the <Share size={14} weight="bold" className="inline-block mx-0.5 -translate-y-[2px]" /> Share button at the bottom.</li>
                  <li>Scroll down and tap <span className="inline-flex items-center gap-1 font-semibold text-white"><Plus size={12} weight="bold" /> Add to Home Screen</span>.</li>
                  <li>Tap <strong className="text-white">Add</strong> in the top-right.</li>
                </ol>
                <p className="text-xs text-[#A3A3A3] mt-3 leading-relaxed">
                  The app icon will appear on your home screen and launch full-screen like a native app.
                </p>
              </div>
            )}

            {active === 'android' && (
              <div data-testid="install-pane-android">
                <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-3">Android — Chrome / Brave / Edge</h3>
                <ol className="text-sm text-[#CFCFCF] leading-relaxed space-y-2 list-decimal list-inside marker:text-[#007AFF] marker:font-bold">
                  <li>Open Soccer Scout 11 in <strong className="text-white">Chrome</strong> (or Brave / Edge / Samsung Internet).</li>
                  <li>Wait a moment — the <strong className="text-white">Install App</strong> banner usually pops up automatically.</li>
                  <li>If it doesn't, tap the <GoogleChromeLogo size={14} weight="bold" className="inline-block mx-0.5 -translate-y-[2px]" /> 3-dot menu (top-right) and choose <strong className="text-white">Install app</strong>.</li>
                </ol>
                <div className="mt-4 pt-3 border-t border-white/10">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-white mb-2">DuckDuckGo Browser</h4>
                  <ol className="text-sm text-[#CFCFCF] leading-relaxed space-y-2 list-decimal list-inside marker:text-[#A855F7] marker:font-bold">
                    <li>Tap the <DotsThree size={14} weight="bold" className="inline-block mx-0.5 -translate-y-[1px]" /> menu (bottom-right).</li>
                    <li>Tap <strong className="text-white">Add to Home Screen</strong>.</li>
                  </ol>
                </div>
                <div className="mt-4 pt-3 border-t border-white/10">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-white mb-2">Firefox</h4>
                  <ol className="text-sm text-[#CFCFCF] leading-relaxed space-y-2 list-decimal list-inside marker:text-[#FBBF24] marker:font-bold">
                    <li>Tap the <DotsThreeVertical size={14} weight="bold" className="inline-block mx-0.5 -translate-y-[1px]" /> menu (top-right).</li>
                    <li>Tap <strong className="text-white">Install</strong>.</li>
                  </ol>
                </div>
              </div>
            )}

            {active === 'desktop' && (
              <div data-testid="install-pane-desktop">
                <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-3">Desktop — Chrome / Edge / Brave</h3>
                <ol className="text-sm text-[#CFCFCF] leading-relaxed space-y-2 list-decimal list-inside marker:text-[#007AFF] marker:font-bold">
                  <li>Look for the <strong className="text-white">install icon</strong> in the address bar (looks like a monitor with a down arrow, usually on the right side).</li>
                  <li>Click it, then click <strong className="text-white">Install</strong>.</li>
                  <li>Alternatively: 3-dot menu → <strong className="text-white">Cast, save, and share</strong> → <strong className="text-white">Install page as app</strong> (Chrome) or <strong className="text-white">Apps → Install this site as an app</strong> (Edge).</li>
                </ol>
                <p className="text-xs text-[#A3A3A3] mt-3 leading-relaxed">
                  Firefox on desktop doesn't support installing PWAs as standalone apps yet — bookmark the page instead.
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-white/10 px-5 py-3 text-[10px] text-[#666] tracking-[0.2em] uppercase">
          Share the QR code with your assistant coach to install on their device too.
        </div>
      </div>
    </div>
  );
};

export default InstallGuideModal;
