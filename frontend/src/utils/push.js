import axios from 'axios';
import { API, getAuthHeader } from '../App';

/**
 * Web Push helpers — keep CoachPulseCard.js focused on UI by putting the
 * browser-API plumbing here.
 */

export const isPushSupported = () =>
  typeof window !== 'undefined' &&
  'serviceWorker' in navigator &&
  'PushManager' in window &&
  'Notification' in window;

export const isStandalonePwa = () =>
  typeof window !== 'undefined' &&
  (window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator.standalone === true);

export const isIOS = () => {
  const ua = navigator.userAgent || '';
  return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
};

// iOS Safari requires the app to be installed (added to home screen) before push works.
export const isIosButNotInstalled = () => isIOS() && !isStandalonePwa();

const urlBase64ToUint8Array = (base64String) => {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const arr = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) arr[i] = rawData.charCodeAt(i);
  return arr;
};

const getRegistration = async () => {
  // Ensure a service worker is registered even if App.js skipped it in dev mode
  let reg = await navigator.serviceWorker.getRegistration();
  if (!reg) {
    reg = await navigator.serviceWorker.register('/service-worker.js');
    await navigator.serviceWorker.ready;
  }
  return reg;
};

/** Returns {granted: bool, reason?: string}. */
export const requestPushPermission = async () => {
  if (!isPushSupported()) return { granted: false, reason: 'Push not supported on this browser' };
  if (isIosButNotInstalled()) return { granted: false, reason: 'Install the app to your home screen first' };
  const current = Notification.permission;
  if (current === 'granted') return { granted: true };
  if (current === 'denied') return { granted: false, reason: 'Permission was previously denied — enable in browser settings' };
  const perm = await Notification.requestPermission();
  return { granted: perm === 'granted', reason: perm === 'granted' ? undefined : 'Permission denied' };
};

export const subscribeToPush = async () => {
  const { data } = await axios.get(`${API}/push/vapid-key`);
  if (!data.configured) throw new Error('Push not configured on the server');

  const reg = await getRegistration();
  const existing = await reg.pushManager.getSubscription();
  const sub =
    existing ||
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.public_key),
    }));

  // Send to backend
  const json = sub.toJSON();
  await axios.post(
    `${API}/push/subscribe`,
    { endpoint: json.endpoint, keys: json.keys },
    { headers: getAuthHeader() }
  );
  return sub;
};

export const unsubscribeFromPush = async () => {
  if (!isPushSupported()) return;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  const endpoint = sub.endpoint;
  try {
    await sub.unsubscribe();
  } catch (err) { console.warn('[push] sub.unsubscribe() failed:', err); }
  try {
    await axios.post(
      `${API}/push/unsubscribe`,
      { endpoint },
      { headers: getAuthHeader() }
    );
  } catch (err) { console.warn('[push] /push/unsubscribe API call failed:', err); }
};

export const sendTestPush = async () => {
  const res = await axios.post(`${API}/push/send-test`, {}, { headers: getAuthHeader() });
  return res.data;
};

export const getSubscriptionCount = async () => {
  try {
    const res = await axios.get(`${API}/push/subscriptions`, { headers: getAuthHeader() });
    return res.data.count || 0;
  } catch {
    return 0;
  }
};

/**
 * Fire a *local* notification from the main thread via the active service worker.
 * Works in foreground & background tabs (Android Chrome requires SW.showNotification
 * rather than `new Notification()`). Use this for "this thing finished" toasts
 * that originate in the client — not server-pushed events.
 *
 * Returns true if the notification was fired, false otherwise (permission denied
 * or no SW available). Errors are swallowed so the caller can fire-and-forget.
 */
export const showLocalNotification = async (title, { body, url = '/', tag } = {}) => {
  try {
    if (!isPushSupported() || Notification.permission !== 'granted') return false;
    const reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return false;
    await reg.showNotification(title, {
      body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url },
      tag: tag || 'soccer-scout-local',
      renotify: true,
    });
    return true;
  } catch (err) {
    console.warn('[push] showLocalNotification failed:', err);
    return false;
  }
};
