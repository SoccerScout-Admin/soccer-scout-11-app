import { useEffect, useMemo, useState } from 'react';
import { DeviceMobile, X, Plus, Share, DotsThreeVertical, DotsThree } from '@phosphor-icons/react';

const DISMISS_KEY = 'pwa-install-dismissed';
const DISMISS_DAYS = 14;

const isStandalone = () => {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  );
};

/**
 * Best-effort browser/UA detection so we can render install instructions that
 * actually match what the user is seeing.
 *
 * We don't sniff for happy path features — we sniff specifically to detect
 * cases where `beforeinstallprompt` will NEVER fire (iOS WebKit, DuckDuckGo,
 * Firefox, embedded Instagram/Facebook webviews) and surface a manual hint.
 */
const detectBrowser = () => {
  if (typeof navigator === 'undefined') return { os: 'unknown', browser: 'unknown' };
  const ua = navigator.userAgent || '';

  // OS
  let os = 'desktop';
  if (/iPad|iPhone|iPod/.test(ua) && !window.MSStream) os = 'ios';
  else if (/Android/.test(ua)) os = 'android';

  // Browser — order matters (specific before generic)
  let browser = 'other';
  if (/FBAN|FBAV|FB_IAB|Instagram/i.test(ua)) browser = 'in-app';        // social webview
  else if (/DuckDuckGo|DuckDuckBot/i.test(ua)) browser = 'duckduckgo';
  else if (/Brave/i.test(ua) || (navigator.brave && typeof navigator.brave.isBrave === 'function')) browser = 'brave';
  else if (/Edg\//i.test(ua)) browser = 'edge';
  else if (/SamsungBrowser/i.test(ua)) browser = 'samsung';
  else if (/Firefox/i.test(ua) || /FxiOS/i.test(ua)) browser = 'firefox';
  else if (/CriOS/i.test(ua)) browser = 'chrome';                         // Chrome on iOS
  else if (/Chrome/i.test(ua) && !/Edg\//i.test(ua)) browser = 'chrome';
  else if (/Safari/i.test(ua) && os === 'ios') browser = 'safari';
  else if (/Safari/i.test(ua)) browser = 'safari';

  return { os, browser };
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
 * Install hint specific to the user's browser/OS combo.
 * Returns { steps: ReactNode[] | null, native: bool }.
 *   native=true → `beforeinstallprompt` is expected to fire; we'll show the
 *   one-click Install button instead of manual steps.
 */
const getInstructions = ({ os, browser }) => {
  // iOS — only Safari can install. Chrome / DuckDuckGo / Firefox on iOS
  // are all WebKit wrappers and cannot install PWAs.
  if (os === 'ios') {
    if (browser === 'safari') {
      return {
        native: false,
        steps: [
          <>Tap <Share size={12} weight="bold" className="inline-block mx-0.5 -translate-y-[1px]" /> in Safari's bottom bar</>,
          <>Choose <span className="whitespace-nowrap inline-flex items-center gap-0.5 font-semibold text-white"><Plus size={11} weight="bold" /> Add to Home Screen</span></>,
        ],
      };
    }
    // Any other iOS browser — gently redirect to Safari
    return {
      native: false,
      steps: [
        <>Open this page in <strong className="text-white">Safari</strong> (iOS PWA install requires Safari)</>,
        <>Then tap <Share size={12} weight="bold" className="inline-block mx-0.5 -translate-y-[1px]" /> → <span className="whitespace-nowrap inline-flex items-center gap-0.5 font-semibold text-white"><Plus size={11} weight="bold" /> Add to Home Screen</span></>,
      ],
    };
  }

  // Android — most browsers support the native prompt via `beforeinstallprompt`
  if (os === 'android') {
    if (browser === 'chrome' || browser === 'brave' || browser === 'edge' || browser === 'samsung') {
      return { native: true, steps: null };
    }
    if (browser === 'duckduckgo') {
      return {
        native: false,
        steps: [
          <>Tap the <DotsThree size={14} weight="bold" className="inline-block -translate-y-[1px]" /> menu (bottom-right)</>,
          <>Tap <strong className="text-white">Add to Home Screen</strong></>,
        ],
      };
    }
    if (browser === 'firefox') {
      return {
        native: false,
        steps: [
          <>Tap the <DotsThreeVertical size={14} weight="bold" className="inline-block -translate-y-[1px]" /> menu (top-right)</>,
          <>Tap <strong className="text-white">Install</strong> or <strong className="text-white">Add to Home Screen</strong></>,
        ],
      };
    }
    if (browser === 'in-app') {
      return {
        native: false,
        steps: [
          <>Tap the <DotsThree size={14} weight="bold" className="inline-block -translate-y-[1px]" /> menu in this app</>,
          <>Choose <strong className="text-white">Open in Chrome</strong> (or your default browser)</>,
          <>Then return here — the Install button will appear automatically</>,
        ],
      };
    }
    // Fallback for unknown Android browsers
    return {
      native: false,
      steps: [
        <>Open the browser menu</>,
        <>Look for <strong className="text-white">Install app</strong> or <strong className="text-white">Add to Home Screen</strong></>,
      ],
    };
  }

  // Desktop — Chrome / Edge / Brave / Opera fire `beforeinstallprompt`
  // Firefox doesn't support PWAs at all on desktop; we just hide the prompt.
  if (browser === 'firefox') return { native: false, hidden: true };
  return { native: true, steps: null };
};

const PWAInstallPrompt = () => {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [visible, setVisible] = useState(false);

  const env = useMemo(detectBrowser, []);
  const instructions = useMemo(() => getInstructions(env), [env]);

  useEffect(() => {
    if (isStandalone() || isDismissedRecently() || instructions.hidden) return;

    const handler = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setVisible(true);
    };
    window.addEventListener('beforeinstallprompt', handler);

    // For browsers without `beforeinstallprompt` (iOS, DuckDuckGo, Firefox, in-app),
    // show the manual-instructions card after a short delay so the page can render first.
    let hintTimer;
    if (!instructions.native) {
      hintTimer = setTimeout(() => {
        if (!isStandalone() && !isDismissedRecently()) setVisible(true);
      }, 6000);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', handler);
      if (hintTimer) clearTimeout(hintTimer);
    };
  }, [instructions.native, instructions.hidden]);

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* noop */ }
    setVisible(false);
  };

  const install = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* noop */ }
    setDeferredPrompt(null);
    setVisible(false);
  };

  if (!visible) return null;

  const showNativeButton = instructions.native && deferredPrompt;
  const showManualSteps = !instructions.native && instructions.steps;

  return (
    <div data-testid="pwa-install-prompt"
      className="fixed bottom-4 left-4 right-4 sm:bottom-6 sm:left-auto sm:right-6 sm:w-[420px] z-[150] bg-[#111] border border-[#007AFF]/40 shadow-[0_20px_60px_rgba(0,122,255,0.25)] p-4">
      <button data-testid="pwa-dismiss-btn" onClick={dismiss} aria-label="Dismiss"
        className="absolute top-2 right-2 p-1.5 text-[#666] hover:text-white transition-colors">
        <X size={14} />
      </button>
      <div className="flex gap-3">
        <div className="w-10 h-10 bg-[#007AFF]/15 border border-[#007AFF]/30 flex items-center justify-center flex-shrink-0">
          <DeviceMobile size={20} weight="bold" className="text-[#007AFF]" />
        </div>
        <div className="flex-1 min-w-0 pr-4">
          <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-[#007AFF] mb-1">Install App</div>
          <div className="text-sm font-bold text-white leading-snug mb-2">
            Add Soccer Scout to your home screen
          </div>
          {showNativeButton && (
            <>
              <p className="text-xs text-[#A3A3A3] leading-relaxed mb-3">
                One-tap install for faster access and a native-feeling app icon on the sidelines.
              </p>
              <button data-testid="pwa-install-btn" onClick={install}
                className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider bg-[#007AFF] hover:bg-[#0066DD] text-white px-4 py-2 transition-colors">
                Install
              </button>
            </>
          )}
          {showManualSteps && (
            <ol data-testid="pwa-manual-steps" className="text-xs text-[#A3A3A3] leading-relaxed space-y-1.5 list-decimal list-inside marker:text-[#007AFF] marker:font-bold">
              {instructions.steps.map((step, idx) => (
                <li key={idx}>{step}</li>
              ))}
            </ol>
          )}
          {!showNativeButton && !showManualSteps && (
            <p className="text-xs text-[#A3A3A3] leading-relaxed">
              Look for "Install" or "Add to Home Screen" in your browser menu.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default PWAInstallPrompt;
