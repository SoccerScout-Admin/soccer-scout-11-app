/**
 * Soccer Scout service worker
 *
 * Minimal, network-first worker that ONLY exists to make the PWA installable.
 * We intentionally skip response caching because:
 *   - Video files are large and must always be fresh
 *   - API responses are personalized per user and can't safely be shared
 *   - Coaches need to see the latest AI analysis the moment it finishes
 * The browser's HTTP cache + our hashed build assets already handle static asset freshness.
 */
const VERSION = 'v1-2026-04-30';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Pure pass-through: let the browser handle every request normally.
  // Having this listener at all is what makes Chrome consider the app installable.
});
