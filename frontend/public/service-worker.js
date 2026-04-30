/**
 * Soccer Scout service worker
 *
 * Responsibilities:
 *   1. Make the app installable as a PWA (having a SW is required by Chrome).
 *   2. Handle web push notifications (`push` event) and route clicks to the
 *      relevant URL in the PWA (`notificationclick` event).
 *
 * We intentionally do NOT cache API responses or video files — both are
 * personalized and/or large, so staleness is worse than a network trip.
 */
const VERSION = 'v2-push-2026-04-30';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', () => {
  // No-op — pass-through to network. The registration alone is what makes
  // the app installable; we don't want to cache anything.
});

self.addEventListener('push', (event) => {
  let payload = { title: 'Soccer Scout', body: 'You have a new update.', url: '/' };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch (err) {
    // If the server sent a plain string, treat it as the body
    try { payload.body = event.data?.text() || payload.body; } catch { /* noop */ }
  }

  const { title, body, url } = payload;
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url },
      tag: 'soccer-scout-push',
      renotify: false,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/';
  event.waitUntil(
    (async () => {
      const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
      // If a Soccer Scout tab is already open, focus it and navigate
      for (const client of allClients) {
        if (client.url.includes(self.registration.scope)) {
          await client.focus();
          if ('navigate' in client) {
            try { await client.navigate(targetUrl); } catch { /* cross-origin guard */ }
          }
          return;
        }
      }
      // Otherwise open a new window
      await clients.openWindow(targetUrl);
    })()
  );
});
