import { useEffect, useState } from 'react';
import { DeviceMobile, X, Plus, Share } from '@phosphor-icons/react';

const DISMISS_KEY = 'pwa-install-dismissed';
const DISMISS_DAYS = 14;

const isStandalone = () => {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  );
};

const isIOS = () => {
  const ua = navigator.userAgent || '';
  return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
};

const isDismissedRecently = () => {
  try {
    const raw = localStorage.getItem(DISMISS_KEY);
    if (!raw) return false;
    const ts = parseInt(raw, 10);
    if (Number.isNaN(ts)) return false;
    return (Date.now() - ts) / (1000 * 60 * 60 * 24) < DISMISS_DAYS;
  } catch {
    return false;
  }
};

/**
 * Non-intrusive install prompt.
 * - Chrome / Edge / Android: captures `beforeinstallprompt`, shows a single toast
 *   with an "Install" button that triggers the native UA install UI.
 * - iOS Safari: no native prompt exists, so we render a one-sentence hint with the
 *   Share + Add-to-Home-Screen icons.
 * - Dismissals are remembered for 14 days so we never nag.
 */
const PWAInstallPrompt = () => {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [visible, setVisible] = useState(false);
  const [showIosHint, setShowIosHint] = useState(false);

  useEffect(() => {
    if (isStandalone() || isDismissedRecently()) return;

    const handler = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setVisible(true);
    };
    window.addEventListener('beforeinstallprompt', handler);

    // iOS fallback — show the hint after 6s if no native prompt fired and we're on iOS
    let iosTimer;
    if (isIOS()) {
      iosTimer = setTimeout(() => {
        if (!isStandalone() && !isDismissedRecently()) {
          setShowIosHint(true);
          setVisible(true);
        }
      }, 6000);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', handler);
      if (iosTimer) clearTimeout(iosTimer);
    };
  }, []);

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* noop */ }
    setVisible(false);
  };

  const install = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    // regardless of outcome, remember to avoid re-prompting
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* noop */ }
    setDeferredPrompt(null);
    setVisible(false);
    return outcome;
  };

  if (!visible) return null;

  return (
    <div data-testid="pwa-install-prompt"
      className="fixed bottom-6 left-6 right-6 sm:left-auto sm:right-6 sm:w-[420px] z-[150] bg-[#111] border border-[#007AFF]/40 shadow-[0_20px_60px_rgba(0,122,255,0.25)] p-4 transition-opacity duration-300"
      style={{ opacity: visible ? 1 : 0 }}>
      <button data-testid="pwa-dismiss-btn" onClick={dismiss} aria-label="Dismiss"
        className="absolute top-2 right-2 p-1 text-[#666] hover:text-white transition-colors">
        <X size={14} />
      </button>
      <div className="flex gap-3">
        <div className="w-10 h-10 bg-[#007AFF]/15 border border-[#007AFF]/30 flex items-center justify-center flex-shrink-0">
          <DeviceMobile size={20} weight="bold" className="text-[#007AFF]" />
        </div>
        <div className="flex-1 min-w-0 pr-4">
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-[#007AFF] mb-1">Install App</div>
          <div className="text-sm font-bold text-white leading-snug mb-1">
            Add Soccer Scout to your home screen
          </div>
          {showIosHint ? (
            <div className="text-xs text-[#A3A3A3] leading-relaxed">
              In Safari, tap <Share size={12} weight="bold" className="inline-block mx-0.5 -translate-y-[1px]" /> then <span className="whitespace-nowrap inline-flex items-center gap-0.5">
                <Plus size={11} weight="bold" className="inline-block" /> Add to Home Screen
              </span>.
            </div>
          ) : (
            <div className="text-xs text-[#A3A3A3] leading-relaxed">
              One-tap install for faster access and a native-feeling app icon on the sidelines.
            </div>
          )}
          {!showIosHint && deferredPrompt && (
            <button data-testid="pwa-install-btn" onClick={install}
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider bg-[#007AFF] hover:bg-[#0066DD] text-white px-4 py-2 transition-colors">
              Install
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default PWAInstallPrompt;
