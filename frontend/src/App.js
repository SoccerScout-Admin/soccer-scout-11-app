import { useState, useEffect } from 'react';
import '@/App.css';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import axios from 'axios';
import AuthPage from './pages/AuthPage';
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
    setIsAuthenticated(!!token);
  }, []);

  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<AuthPage setIsAuthenticated={setIsAuthenticated} />} />
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
          <Route
            path="/player/:playerId"
            element={
              <ProtectedRoute>
                <PlayerProfile />
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
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
