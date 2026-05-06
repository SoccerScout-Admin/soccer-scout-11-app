import { useState, useEffect } from 'react';
import '@/App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import axios from 'axios';
import AuthPage from './pages/AuthPage';
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

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const getAuthHeader = () => {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const getCurrentUser = () => {
  const user = localStorage.getItem('user');
  return user ? JSON.parse(user) : null;
};

const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/auth" replace />;
  }
  return children;
};

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) { setIsAuthenticated(false); return; }
    // Revalidate token on mount — if 401, drop stale session.
    // Also syncs role/name changes (e.g. admin promotion) without logout/login.
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
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
        <Routes>
          <Route path="/auth" element={<AuthPage setIsAuthenticated={setIsAuthenticated} />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route
            path="/"
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
