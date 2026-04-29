import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Plus, Shield, Users, Trash, PencilSimple, Upload, CalendarBlank } from '@phosphor-icons/react';

const ClubManager = () => {
  const navigate = useNavigate();
  const [clubs, setClubs] = useState([]);
  const [teams, setTeams] = useState([]);
  const [showClubForm, setShowClubForm] = useState(false);
  const [showTeamForm, setShowTeamForm] = useState(false);
  const [clubName, setClubName] = useState('');
  const [teamForm, setTeamForm] = useState({ name: '', season: '', club: '' });
  const [editingClub, setEditingClub] = useState(null);
  const [uploadingLogo, setUploadingLogo] = useState(null);

  useEffect(() => { fetchClubs(); fetchTeams(); }, []);

  const fetchClubs = async () => {
    try {
      const res = await axios.get(`${API}/clubs`, { headers: getAuthHeader() });
      setClubs(res.data);
    } catch (err) { console.error('Failed to fetch clubs:', err); }
  };

  const fetchTeams = async () => {
    try {
      const res = await axios.get(`${API}/teams`, { headers: getAuthHeader() });
      setTeams(res.data);
    } catch (err) { console.error('Failed to fetch teams:', err); }
  };

  const handleCreateClub = async (e) => {
    e.preventDefault();
    if (!clubName.trim()) return;
    try {
      if (editingClub) {
        await axios.patch(`${API}/clubs/${editingClub.id}?name=${encodeURIComponent(clubName)}`, {}, { headers: getAuthHeader() });
      } else {
        await axios.post(`${API}/clubs?name=${encodeURIComponent(clubName)}`, {}, { headers: getAuthHeader() });
      }
      setClubName('');
      setEditingClub(null);
      setShowClubForm(false);
      fetchClubs();
    } catch (err) { console.error('Failed to save club:', err); }
  };

  const handleCreateTeam = async (e) => {
    e.preventDefault();
    if (!teamForm.name.trim() || !teamForm.season.trim()) return;
    try {
      const params = new URLSearchParams({ name: teamForm.name, season: teamForm.season });
      if (teamForm.club) params.append('club', teamForm.club);
      await axios.post(`${API}/teams?${params.toString()}`, {}, { headers: getAuthHeader() });
      setTeamForm({ name: '', season: '', club: '' });
      setShowTeamForm(false);
      fetchTeams();
    } catch (err) { console.error('Failed to create team:', err); }
  };

  const handleDeleteClub = async (clubId) => {
    if (!window.confirm('Delete this club? Teams will be unlinked.')) return;
    try {
      await axios.delete(`${API}/clubs/${clubId}`, { headers: getAuthHeader() });
      fetchClubs();
      fetchTeams();
    } catch (err) { console.error('Failed to delete club:', err); }
  };

  const handleDeleteTeam = async (teamId) => {
    if (!window.confirm('Delete this team? Players will be unlinked.')) return;
    try {
      await axios.delete(`${API}/teams/${teamId}`, { headers: getAuthHeader() });
      fetchTeams();
    } catch (err) { console.error('Failed to delete team:', err); }
  };

  const handleLogoUpload = async (clubId, file) => {
    if (!file) return;
    setUploadingLogo(clubId);
    try {
      const formData = new FormData();
      formData.append('file', file);
      await axios.post(`${API}/clubs/${clubId}/logo`, formData, { headers: getAuthHeader() });
      fetchClubs();
    } catch (err) {
      alert('Failed to upload logo: ' + (err.response?.data?.detail || err.message));
    } finally {
      setUploadingLogo(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <button data-testid="back-to-dashboard-btn" onClick={() => navigate('/')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <div>
            <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Club & Team Management</h1>
            <p className="text-xs text-[#A3A3A3] tracking-wider">Organize your clubs, teams, and seasons</p>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-10">
        {/* Clubs Section */}
        <section data-testid="clubs-section">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <Shield size={24} className="text-[#007AFF]" />
              <h2 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Soccer Clubs</h2>
              <span className="text-xs text-[#A3A3A3] bg-white/5 px-2 py-1">{clubs.length}</span>
            </div>
            <button data-testid="add-club-btn" onClick={() => { setShowClubForm(true); setEditingClub(null); setClubName(''); }}
              className="flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-5 py-2.5 font-bold tracking-wider uppercase text-xs transition-colors">
              <Plus size={16} weight="bold" /> Add Club
            </button>
          </div>

          {/* Club Create/Edit Form */}
          {showClubForm && (
            <form onSubmit={handleCreateClub} data-testid="club-form"
              className="bg-[#141414] border border-white/10 p-6 mb-6">
              <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-4">
                {editingClub ? 'Edit Club' : 'New Soccer Club'}
              </h3>
              <div className="flex gap-3">
                <input data-testid="club-name-input" type="text" value={clubName}
                  onChange={(e) => setClubName(e.target.value)}
                  placeholder="e.g., Lakeshore FC"
                  className="flex-1 bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
                <button data-testid="submit-club-btn" type="submit"
                  className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                  {editingClub ? 'Save' : 'Create'}
                </button>
                <button type="button" onClick={() => setShowClubForm(false)}
                  className="px-4 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold uppercase">
                  Cancel
                </button>
              </div>
            </form>
          )}

          {/* Club Cards */}
          {clubs.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-white/10">
              <Shield size={48} className="text-[#A3A3A3] mx-auto mb-3" />
              <p className="text-[#A3A3A3]">No clubs yet</p>
              <p className="text-xs text-[#666]">Add your soccer club to organize teams under it</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {clubs.map(club => (
                <div key={club.id} data-testid={`club-card-${club.id}`}
                  className="bg-[#141414] border border-white/10 p-5 hover:bg-[#1A1A1A] transition-colors group">
                  <div className="flex items-start gap-4">
                    {/* Logo */}
                    <div className="w-16 h-16 flex-shrink-0 bg-[#0A0A0A] border border-white/10 flex items-center justify-center overflow-hidden relative">
                      {club.logo_url ? (
                        <img src={`${API.replace('/api', '')}${club.logo_url}`} alt={club.name}
                          className="w-full h-full object-contain" />
                      ) : (
                        <Shield size={28} className="text-[#333]" />
                      )}
                      <label data-testid={`upload-logo-${club.id}-btn`}
                        className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer">
                        {uploadingLogo === club.id ? (
                          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <Upload size={18} className="text-white" />
                        )}
                        <input type="file" accept="image/*" className="hidden"
                          onChange={(e) => handleLogoUpload(club.id, e.target.files[0])} />
                      </label>
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-lg font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>{club.name}</h3>
                      <p className="text-xs text-[#A3A3A3] mt-1">
                        {club.team_count || 0} team{(club.team_count || 0) !== 1 ? 's' : ''}
                      </p>
                    </div>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button data-testid={`edit-club-${club.id}-btn`}
                        onClick={() => { setEditingClub(club); setClubName(club.name); setShowClubForm(true); }}
                        className="p-1.5 text-[#A3A3A3] hover:text-white hover:bg-white/10 transition-colors">
                        <PencilSimple size={14} />
                      </button>
                      <button data-testid={`delete-club-${club.id}-btn`}
                        onClick={() => handleDeleteClub(club.id)}
                        className="p-1.5 text-[#A3A3A3] hover:text-[#EF4444] hover:bg-[#EF4444]/10 transition-colors">
                        <Trash size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Teams Section */}
        <section data-testid="teams-section">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <Users size={24} className="text-[#39FF14]" />
              <h2 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Teams & Seasons</h2>
              <span className="text-xs text-[#A3A3A3] bg-white/5 px-2 py-1">{teams.length}</span>
            </div>
            <button data-testid="add-team-btn" onClick={() => setShowTeamForm(true)}
              className="flex items-center gap-2 bg-[#39FF14] hover:bg-[#2FD910] text-black px-5 py-2.5 font-bold tracking-wider uppercase text-xs transition-colors">
              <Plus size={16} weight="bold" /> Add Team
            </button>
          </div>

          {/* Team Create Form */}
          {showTeamForm && (
            <form onSubmit={handleCreateTeam} data-testid="team-form"
              className="bg-[#141414] border border-white/10 p-6 mb-6">
              <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-4">New Team</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Team Name *</label>
                  <input data-testid="team-name-input" type="text" value={teamForm.name}
                    onChange={(e) => setTeamForm({ ...teamForm, name: e.target.value })}
                    placeholder="e.g., 2007 B Premier"
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#39FF14] focus:outline-none" required />
                </div>
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Season *</label>
                  <input data-testid="team-season-input" type="text" value={teamForm.season}
                    onChange={(e) => setTeamForm({ ...teamForm, season: e.target.value })}
                    placeholder="e.g., 2025/26"
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#39FF14] focus:outline-none" required />
                </div>
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Club</label>
                  <select data-testid="team-club-select" value={teamForm.club}
                    onChange={(e) => setTeamForm({ ...teamForm, club: e.target.value })}
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#39FF14] focus:outline-none">
                    <option value="">No club</option>
                    {clubs.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="flex gap-3">
                <button data-testid="submit-team-btn" type="submit"
                  className="bg-[#39FF14] hover:bg-[#2FD910] text-black px-6 py-2.5 font-bold tracking-wider uppercase text-xs transition-colors">
                  Create Team
                </button>
                <button type="button" onClick={() => setShowTeamForm(false)}
                  className="px-4 py-2.5 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold uppercase">
                  Cancel
                </button>
              </div>
            </form>
          )}

          {/* Team List */}
          {teams.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-white/10">
              <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
              <p className="text-[#A3A3A3]">No teams yet</p>
              <p className="text-xs text-[#666]">Create a team to start registering players</p>
            </div>
          ) : (
            <div className="space-y-3">
              {teams.map(team => {
                const clubInfo = clubs.find(c => c.id === team.club);
                return (
                  <div key={team.id} data-testid={`team-card-${team.id}`}
                    onClick={() => navigate(`/team/${team.id}`)}
                    className="bg-[#141414] border border-white/10 p-5 flex items-center gap-4 hover:bg-[#1A1A1A] transition-colors group cursor-pointer">
                    {/* Club Logo */}
                    <div className="w-10 h-10 flex-shrink-0 bg-[#0A0A0A] border border-white/5 flex items-center justify-center overflow-hidden">
                      {clubInfo?.logo_url ? (
                        <img src={`${API.replace('/api', '')}${clubInfo.logo_url}`} alt=""
                          className="w-full h-full object-contain" />
                      ) : (
                        <Shield size={18} className="text-[#333]" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-base font-bold text-white truncate">{team.name}</h3>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="flex items-center gap-1 text-xs text-[#A3A3A3]">
                          <CalendarBlank size={12} /> {team.season}
                        </span>
                        {clubInfo && (
                          <span className="text-xs text-[#007AFF]">{clubInfo.name}</span>
                        )}
                        <span className="text-xs text-[#666]">{team.player_count || 0} players</span>
                      </div>
                    </div>
                    <button data-testid={`delete-team-${team.id}-btn`}
                      onClick={() => handleDeleteTeam(team.id)}
                      className="p-2 text-[#A3A3A3] hover:text-[#EF4444] hover:bg-[#EF4444]/10 transition-colors opacity-0 group-hover:opacity-100">
                      <Trash size={16} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default ClubManager;
