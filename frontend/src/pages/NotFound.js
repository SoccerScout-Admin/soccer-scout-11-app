import { Link, useLocation } from 'react-router-dom';

/**
 * Catch-all 404 page. Prevents the "blank black screen" a user hits when they
 * mistype a route (e.g. /admin/processing_events with an underscore instead of
 * the real /admin/processing-events). Matches the app's dark brand theme.
 */
export default function NotFound() {
  const location = useLocation();

  return (
    <div
      data-testid="not-found-page"
      className="min-h-screen bg-[#0A0A0A] text-white flex flex-col items-center justify-center px-6 text-center"
    >
      <img
        src="/logo-mark-256.png"
        alt="Soccer Scout 11"
        className="w-24 h-auto opacity-90 mb-8"
        data-testid="not-found-logo"
      />
      <p className="text-[#38BDF8] font-semibold tracking-[0.3em] text-sm mb-3">
        404
      </p>
      <h1 className="text-3xl sm:text-4xl font-bold mb-4">
        This page doesn&apos;t exist
      </h1>
      <p className="text-zinc-400 max-w-md mb-2">
        We couldn&apos;t find a page matching{' '}
        <code className="text-zinc-200 bg-zinc-800 px-1.5 py-0.5 rounded text-sm" data-testid="not-found-path">
          {location.pathname}
        </code>
        .
      </p>
      <p className="text-zinc-500 text-sm max-w-md mb-8">
        Double-check the address — links use hyphens, not underscores
        (e.g. <span className="text-zinc-300">/admin/processing-events</span>).
      </p>
      <div className="flex flex-wrap gap-3 justify-center">
        <Link
          to="/dashboard"
          data-testid="not-found-dashboard-btn"
          className="px-6 py-2.5 rounded-full bg-[#38BDF8] text-black font-semibold hover:bg-[#0EA5E9] transition-colors"
        >
          Back to dashboard
        </Link>
        <Link
          to="/admin/processing-events"
          data-testid="not-found-processing-events-btn"
          className="px-6 py-2.5 rounded-full border border-zinc-700 text-zinc-200 font-semibold hover:bg-zinc-800 transition-colors"
        >
          Processing events
        </Link>
      </div>
    </div>
  );
}
