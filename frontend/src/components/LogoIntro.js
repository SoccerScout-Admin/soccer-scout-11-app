import { useEffect, useState, useCallback } from 'react';
import '../styles/logo-intro.css';

const SESSION_KEY = 'ss11-splash-played';

/**
 * Full-screen Soccer Scout 11 brand intro splash.
 * Plays a premium S11 mark reveal once per browser session (sessionStorage
 * gated), then fades out to reveal the app. Click anywhere to skip.
 * Skipped entirely for users who prefer reduced motion.
 */
const LogoIntro = () => {
  const [show, setShow] = useState(() => {
    try {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
      return !sessionStorage.getItem(SESSION_KEY);
    } catch {
      return false;
    }
  });
  const [leaving, setLeaving] = useState(false);

  const dismiss = useCallback(() => {
    setLeaving(true);
    window.setTimeout(() => setShow(false), 560);
  }, []);

  useEffect(() => {
    if (!show) return undefined;
    try { sessionStorage.setItem(SESSION_KEY, '1'); } catch { /* storage blocked */ }
    const tHold = window.setTimeout(() => setLeaving(true), 2000);
    const tDone = window.setTimeout(() => setShow(false), 2600);
    return () => { window.clearTimeout(tHold); window.clearTimeout(tDone); };
  }, [show]);

  if (!show) return null;

  return (
    <div
      data-testid="logo-intro-splash"
      className={`ss11-splash${leaving ? ' leaving' : ''}`}
      onClick={dismiss}
      role="presentation"
      aria-hidden="true"
    >
      <div className="ss11-splash-inner">
        <div className="ss11-mark-wrap">
          <img src="/logo-mark-256.png" alt="Soccer Scout 11" className="ss11-mark" />
          <span
            className="ss11-shine"
            aria-hidden="true"
            style={{
              WebkitMaskImage: 'url(/logo-mark-256.png)',
              maskImage: 'url(/logo-mark-256.png)',
            }}
          />
        </div>
        <div className="ss11-wordmark">SOCCER<span> SCOUT 11</span></div>
        <div className="ss11-tagline">Analyze &middot; Identify &middot; Elevate</div>
        <div className="ss11-divider" />
      </div>
    </div>
  );
};

export default LogoIntro;
