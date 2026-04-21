import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import { Play, Plus, SignOut, VideoCamera, ChartBar, CalendarBlank, Trophy } from '@phosphor-icons/react';

const Dashboard = () => {
  const [matches, setMatches] = useState([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [formData, setFormData] = useState({
    team_home: '',
    team_away: '',
    date: '',
    competition: ''
  });
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const user = getCurrentUser();

  useEffect(() => {
    fetchMatches();
  }, []);

  const fetchMatches = async () => {
    try {
      const response = await axios.get(`${API}/matches`, { headers: getAuthHeader() });
      setMatches(response.data);
    } catch (err) {
      console.error('Failed to fetch matches:', err);
    }
  };

  const handleCreateMatch = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API}/matches`, formData, { headers: getAuthHeader() });
      setShowCreateModal(false);
      setFormData({ team_home: '', team_away: '', date: '', competition: '' });
      fetchMatches();
    } catch (err) {
      console.error('Failed to create match:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    navigate('/auth');
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Play size={32} weight="fill" className="text-[#007AFF]" />
            <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>SOCCER SCOUT</h1>
          </div>
          <div className="flex items-center gap-6">
            <div className="text-right">
              <p className="text-sm text-[#A3A3A3]">{user?.name}</p>
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{user?.role}</p>
            </div>
            <button
              data-testid="logout-btn"
              onClick={handleLogout}
              className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10"
            >
              <SignOut size={24} className="text-[#A3A3A3]" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-4xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Match Library</h2>
            <p className="text-[#A3A3A3] tracking-wide">Manage and analyze your soccer matches</p>
          </div>
          <button
            data-testid="create-match-btn"
            onClick={() => setShowCreateModal(true)}
            className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors flex items-center gap-2"
          >
            <Plus size={24} weight="bold" />
            New Match
          </button>
        </div>

        {matches.length === 0 ? (
          <div className="text-center py-20">
            <VideoCamera size={80} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-xl text-[#A3A3A3] mb-2">No matches yet</p>
            <p className="text-sm text-[#A3A3A3]">Create your first match to start analyzing</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {matches.map((match) => (
              <div
                key={match.id}
                data-testid={`match-card-${match.id}`}
                onClick={() => navigate(`/match/${match.id}`)}
                className="bg-[#141414] border border-white/10 p-6 hover:bg-[#1F1F1F] transition-colors cursor-pointer"
              >
                <div className="flex items-center gap-2 mb-4">
                  <Trophy size={20} className="text-[#007AFF]" />
                  <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{match.competition || 'Friendly'}</p>
                </div>
                <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                  {match.team_home} vs {match.team_away}
                </h3>
                <div className="flex items-center gap-2 text-sm text-[#A3A3A3]">
                  <CalendarBlank size={16} />
                  <span>{new Date(match.date).toLocaleDateString()}</span>
                </div>
                {match.video_id && (
                  <div className="mt-4">
                    {match.processing_status === 'completed' ? (
                      <div className="flex items-center gap-2 text-[#4ADE80] text-sm">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        <span>Analysis Ready</span>
                      </div>
                    ) : match.processing_status === 'processing' || match.processing_status === 'queued' ? (
                      <div className="flex items-center gap-2 text-[#007AFF] text-sm">
                        <div className="w-3 h-3 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
                        <span>Processing ({match.processing_progress || 0}%)</span>
                      </div>
                    ) : match.processing_status === 'failed' ? (
                      <div className="flex items-center gap-2 text-[#EF4444] text-sm">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
                        <span>Processing Failed</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 text-[#39FF14] text-sm">
                        <VideoCamera size={16} />
                        <span>Video uploaded</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      {showCreateModal && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-6 z-50">
          <div className="bg-[#141414] border border-white/10 w-full max-w-lg p-8">
            <h3 className="text-3xl font-bold mb-6" style={{ fontFamily: 'Bebas Neue' }}>Create New Match</h3>
            <form onSubmit={handleCreateMatch} className="space-y-4">
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Home Team</label>
                <input
                  data-testid="home-team-input"
                  type="text"
                  value={formData.team_home}
                  onChange={(e) => setFormData({ ...formData, team_home: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Away Team</label>
                <input
                  data-testid="away-team-input"
                  type="text"
                  value={formData.team_away}
                  onChange={(e) => setFormData({ ...formData, team_away: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Date</label>
                <input
                  data-testid="match-date-input"
                  type="date"
                  value={formData.date}
                  onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Competition</label>
                <input
                  data-testid="competition-input"
                  type="text"
                  value={formData.competition}
                  onChange={(e) => setFormData({ ...formData, competition: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  placeholder="e.g., Premier League, Champions League"
                />
              </div>
              <div className="flex gap-4 mt-6">
                <button
                  data-testid="cancel-create-btn"
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors"
                >
                  Cancel
                </button>
                <button
                  data-testid="submit-create-btn"
                  type="submit"
                  disabled={loading}
                  className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors disabled:opacity-50"
                >
                  {loading ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
