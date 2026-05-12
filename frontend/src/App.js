import { useState, useEffect } from 'react';
import '@/App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import axios from 'axios';
import AuthPage from './pages/AuthPage';
import LandingPage from './pages/LandingPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import Dashboard from './pages/Dashboard';
import MatchDetail from './pages/MatchDetail';
import VideoAnalysis from './pages/VideoAnalysis';
import SharedView from './pages/SharedView';
import SharedClipView from './pages/SharedClipView';
import ClubManager from './pages/ClubManager';
import TeamRoster from './pages/TeamRoster';
import SharedTeamView from './pages/SharedTeamView';
import PlayerProfile from './pages/PlayerProfile';
import SharedPlayerProfile from './pages/SharedPlayerProfile';
import SharedClipCollectionView from './pages/SharedClipCollectionView';
import SharedClubView from './pages/SharedClubView';
import SharedMatchRecap from './pages/SharedMatchRecap';
import SharedHighlightReel from './pages/SharedHighlightReel';
import HighlightReelsBrowse from './pages/HighlightReelsBrowse';
import MatchInsights from './pages/MatchInsights';
import SeasonTrends from './pages/SeasonTrends';
import PlayerSeasonTrends from './pages/PlayerSeasonTrends';
import CoachNetwork from './pages/CoachNetwork';
import MentionsInbox from './pages/MentionsInbox';
import AdminUsers from './pages/AdminUsers';
import AdminClaim from './pages/AdminClaim';
import AdminScouts from './pages/AdminScouts';
import ScoutBrowse from './pages/ScoutBrowse';
import ScoutListingDetail from './pages/ScoutListingDetail';
import ScoutListingForm from './pages/ScoutListingForm';
import ScoutMyListings from './pages/ScoutMyListings';
import Messages from './pages/Messages';
import PWAInstallPrompt from './components/PWAInstallPrompt';
import DiskPressureBanner from './components/DiskPressureBanner';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// AUTH MIGRATION (iter52): we're moving from localStorage tokens to httpOnly cookies
// for XSS protection. During the transition both work — the backend reads the cookie
// first and falls back to the Authorization header. After all existing users have
// logged in at least once (refreshing their cookie), we can drop the header path.
//
// Sending cookies on every API call requires withCredentials. Set it globally so
// every existing axios call gets it without having to touch ~150 call sites.
axios.defaults.withCredentials = true;

// CSRF protection (iter54): the backend pairs the httpOnly access_token cookie
// with a JS-readable csrf_token cookie. We echo that cookie value back in the
// X-CSRF-Token header on every unsafe-method request (POST/PUT/PATCH/DELETE).
// The backend rejects (403) any cookie-authenticated unsafe-method call that
// doesn't match. A cross-origin attacker can't read the cookie (SOP blocks
// document.cookie cross-site), so they can't forge the matching header.
const _CSRF_COOKIE = 'csrf_token';
const _CSRF_HEADER = 'X-CSRF-Token';
const _UNSAFE_METHODS = new Set(['post', 'put', 'patch', 'delete']);

const _readCookie = (name) => {
  if (typeof document === 'undefined') return null;
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
};

axios.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase();
  if (_UNSAFE_METHODS.has(method)) {
    const token = _readCookie(_CSRF_COOKIE);
    if (token) {
      config.headers = config.headers || {};
      config.headers[_CSRF_HEADER] = token;
    }
  }
  return config;
});

export const getAuthHeader = () => {
  // Still returned for backwards compat with the legacy code paths that explicitly
  // attach it. New auth is cookie-driven so this can return {} safely once we drop
  // the localStorage fallback in a future iteration.
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const getCurrentUser = () => {
  const user = localStorage.getItem('user');
  return user ? JSON.parse(user) : null;
};

// `clearSession` — single helper used by logout and 401 cleanup. Calls the
// backend /auth/logout to clear the httpOnly cookie (only the server can clear
// it), then nukes localStorage. Safe to call even without an active session.
export const clearSession = async () => {
  try {
    await axios.post(`${API}/auth/logout`);
  } catch {
    // Network blip or already logged out — proceed with local cleanup either way
  }
  localStorage.removeItem('token');
  localStorage.removeItem('user');
};

const ProtectedRoute = ({ children }) => {
  // Cookie-based sessions can't be inspected from JS (that's the point of
  // httpOnly). Treat the presence of a stored user OR a legacy token as the
  // optimistic "still logged in" signal — the next API call validates it
  // server-side and 401s redirect to /auth via the global axios interceptor.
  const hasLegacyToken = !!localStorage.getItem('token');
  const hasUserCache = !!localStorage.getItem('user');
  if (!hasLegacyToken && !hasUserCache) {
    return <Navigate to="/auth" replace />;
  }
  return children;
};

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    // Validate the session against the backend on every mount. With cookies, we
    // no longer need a token in localStorage — /auth/me will use whichever
    // channel is available (cookie first, then legacy header).
    const hasAnyCredential = !!localStorage.getItem('token') || !!localStorage.getItem('user');
    if (!hasAnyCredential) { setIsAuthenticated(false); return; }
    axios.get(`${API}/auth/me`)
      .then((res) => {
        const u = res.data || {};
        localStorage.setItem('user', JSON.stringify({
          id: u.id, name: u.name, role: u.role,
        }));
        setIsAuthenticated(true);
      })
      .catch((err) => {
        if (err.response?.status === 401) {
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          setIsAuthenticated(false);
        } else {
          // Network/server blip — keep current session, assume authenticated.
          setIsAuthenticated(true);
        }
      });
  }, []);

  // Register service worker so the app is installable AND push-notification-capable
  useEffect(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js').catch(() => {
        // Silently ignore; SW is nice-to-have for installability
      });
    }
  }, []);

  return (
    <div className="App">
      <BrowserRouter>
        <PWAInstallPrompt />
        <DiskPressureBanner />
        <Routes>
          <Route path="/auth" element={<AuthPage setIsAuthenticated={setIsAuthenticated} />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route
            path="/"
            element={
              isAuthenticated ? <Dashboard /> : <LandingPage isAuthenticated={false} />
            }
          />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/match/:matchId"
            element={
              <ProtectedRoute>
                <MatchDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/video/:videoId"
            element={
              <ProtectedRoute>
                <VideoAnalysis />
              </ProtectedRoute>
            }
          />
          <Route path="/shared/:shareToken" element={<SharedView />} />
          <Route path="/shared-team/:shareToken" element={<SharedTeamView />} />
          <Route path="/clip/:shareToken" element={<SharedClipView />} />
          <Route path="/clips/:shareToken" element={<SharedClipCollectionView />} />
          <Route path="/shared-player/:shareToken" element={<SharedPlayerProfile />} />
          <Route path="/shared-club/:shareToken" element={<SharedClubView />} />
          <Route path="/match-recap/:shareToken" element={<SharedMatchRecap />} />
          <Route path="/reel/:shareToken" element={<SharedHighlightReel />} />
          <Route path="/reels" element={<HighlightReelsBrowse />} />
          <Route
            path="/player/:playerId"
            element={
              <ProtectedRoute>
                <PlayerProfile />
              </ProtectedRoute>
            }
          />
          <Route
            path="/match/:matchId/insights"
            element={
              <ProtectedRoute>
                <MatchInsights />
              </ProtectedRoute>
            }
          />
          <Route
            path="/folder/:folderId/trends"
            element={
              <ProtectedRoute>
                <SeasonTrends />
              </ProtectedRoute>
            }
          />
          <Route
            path="/player/:playerId/trends"
            element={
              <ProtectedRoute>
                <PlayerSeasonTrends />
              </ProtectedRoute>
            }
          />
          <Route
            path="/clubs"
            element={
              <ProtectedRoute>
                <ClubManager />
              </ProtectedRoute>
            }
          />
          <Route
            path="/team/:teamId"
            element={
              <ProtectedRoute>
                <TeamRoster />
              </ProtectedRoute>
            }
          />
          <Route
            path="/coach-network"
            element={
              <ProtectedRoute>
                <CoachNetwork />
              </ProtectedRoute>
            }
          />
          <Route
            path="/mentions"
            element={
              <ProtectedRoute>
                <MentionsInbox />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute>
                <AdminUsers />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/claim"
            element={
              <ProtectedRoute>
                <AdminClaim />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/scouts"
            element={
              <ProtectedRoute>
                <AdminScouts />
              </ProtectedRoute>
            }
          />
          <Route path="/scouts" element={<ScoutBrowse />} />
          <Route
            path="/scouts/my"
            element={
              <ProtectedRoute>
                <ScoutMyListings />
              </ProtectedRoute>
            }
          />
          <Route
            path="/messages"
            element={
              <ProtectedRoute>
                <Messages />
              </ProtectedRoute>
            }
          />
          <Route
            path="/messages/:threadId"
            element={
              <ProtectedRoute>
                <Messages />
              </ProtectedRoute>
            }
          />
          <Route
            path="/scouts/new"
            element={
              <ProtectedRoute>
                <ScoutListingForm />
              </ProtectedRoute>
            }
          />
          <Route
            path="/scouts/edit/:listingId"
            element={
              <ProtectedRoute>
                <ScoutListingForm />
              </ProtectedRoute>
            }
          />
          <Route path="/scouts/:listingId" element={<ScoutListingDetail />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
