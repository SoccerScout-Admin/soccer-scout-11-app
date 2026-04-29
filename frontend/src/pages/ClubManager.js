import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Plus, Shield, Users, Trash, PencilSimple, Upload, CalendarBlank, CaretDown, CaretRight, ArrowsClockwise } from '@phosphor-icons/react';

const ClubManager = () => {
  const navigate = useNavigate();
  const [clubs, setClubs] = useState([]);
  const [teams, setTeams] = useState([]);
  const [showClubForm, setShowClubForm] = useState(false);
  const [clubName, setClubName] = useState('');
  const [editingClub, setEditingClub] = useState(null);
  const [uploadingLogo, setUploadingLogo] = useState(null);
  const [collapsedClubs, setCollapsedClubs] = useState({});
  const [teamFormClubId, setTeamFormClubId] = useState(null); // null = closed, '' = unaffiliated, string = club id
  const [teamForm, setTeamForm] = useState({ name: '', season: '' });
  const [promoteTarget, setPromoteTarget] = useState(null); // {team} or null
  const [promoteForm, setPromoteForm] = useState({ new_season: '', new_team_name: '', keep_old: true });
  const [promoting, setPromoting] = useState(false);

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

  const teamsByClub = useMemo(() => {
    const map = { _unaffiliated: [] };
    for (const c of clubs) map[c.id] = [];
    for (const t of teams) {
      if (t.club && map[t.club]) map[t.club].push(t);
      else map._unaffiliated.push(t);
    }
    // Sort teams within each club by season desc, then name
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => (b.season || '').localeCompare(a.season || '') || a.name.localeCompare(b.name));
    }
    return map;
  }, [clubs, teams]);

  const handleSaveClub = async (e) => {
    e.preventDefault();
    if (!clubName.trim()) return;
    try {
      if (editingClub) {
        await axios.patch(`${API}/clubs/${editingClub.id}?name=${encodeURIComponent(clubName)}`, {}, { headers: getAuthHeader() });
      } else {
        await axios.post(`${API}/clubs?name=${encodeURIComponent(clubName)}`, {}, { headers: getAuthHeader() });
      }
      setClubName(''); setEditingClub(null); setShowClubForm(false);
      fetchClubs();
    } catch (err) { console.error('Failed to save club:', err); }
  };

  const handleCreateTeam = async (e) => {
    e.preventDefault();
    if (!teamForm.name.trim() || !teamForm.season.trim()) return;
    try {
      const params = new URLSearchParams({ name: teamForm.name, season: teamForm.season });
      if (teamFormClubId) params.append('club', teamFormClubId);
      await axios.post(`${API}/teams?${params.toString()}`, {}, { headers: getAuthHeader() });
      setTeamForm({ name: '', season: '' });
      setTeamFormClubId(null);
      fetchTeams();
      fetchClubs(); // refresh team_count
    } catch (err) { console.error('Failed to create team:', err); }
  };

  const handleDeleteClub = async (clubId) => {
    if (!window.confirm('Delete this club? Teams will become unaffiliated.')) return;
    try {
      await axios.delete(`${API}/clubs/${clubId}`, { headers: getAuthHeader() });
      fetchClubs(); fetchTeams();
    } catch (err) { console.error('Failed to delete club:', err); }
  };

  const handleDeleteTeam = async (e, teamId) => {
    e.stopPropagation();
    if (!window.confirm('Delete this team? Players will be unlinked.')) return;
    try {
      await axios.delete(`${API}/teams/${teamId}`, { headers: getAuthHeader() });
      fetchTeams(); fetchClubs();
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

  const toggleClub = (id) => setCollapsedClubs(prev => ({ ...prev, [id]: !prev[id] }));

  const openTeamForm = (clubId) => {
    setTeamFormClubId(clubId);
    setTeamForm({ name: '', season: '' });
  };

  const openPromote = (team, e) => {
    e.stopPropagation();
    setPromoteTarget(team);
    // Suggest next season string based on current (e.g., 2025/26 → 2026/27)
    const m = (team.season || '').match(/^(\d{4})\/(\d{2,4})$/);
    let suggested = '';
    if (m) {
      const startY = parseInt(m[1]) + 1;
      const endY = (parseInt(m[2]) + 1).toString().padStart(2, '0').slice(-2);
      suggested = `${startY}/${endY}`;
    }
    setPromoteForm({ new_season: suggested, new_team_name: team.name, keep_old: true });
  };

  const handlePromote = async (e) => {
    e.preventDefault();
    if (!promoteTarget || !promoteForm.new_season.trim()) return;
    setPromoting(true);
    try {
      const res = await axios.post(
        `${API}/teams/${promoteTarget.id}/promote`,
        {
          new_season: promoteForm.new_season.trim(),
          new_team_name: promoteForm.new_team_name.trim() || promoteTarget.name,
          keep_old: promoteForm.keep_old,
        },
        { headers: getAuthHeader() }
      );
      setPromoteTarget(null);
      fetchTeams(); fetchClubs();
      alert(`Promoted ${res.data.promoted_count} player${res.data.promoted_count === 1 ? '' : 's'} to ${promoteForm.new_season}.`);
    } catch (err) {
      alert('Promote failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setPromoting(false);
    }
  };

  const renderTeamRow = (team) => (
    <div key={team.id} data-testid={`team-card-${team.id}`}
      onClick={() => navigate(`/team/${team.id}`)}
      className="bg-[#0F0F0F] border border-white/5 hover:border-[#007AFF]/30 hover:bg-[#1A1A1A] p-4 flex items-center gap-3 cursor-pointer group transition-colors">
      <div className="w-1 h-10 bg-[#007AFF]/40 group-hover:bg-[#007AFF] transition-colors" />
      <div className="flex-1 min-w-0">
        <h4 className="text-base font-semibold text-white truncate">{team.name}</h4>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="flex items-center gap-1 text-xs text-[#A3A3A3]">
            <CalendarBlank size={12} /> {team.season}
          </span>
          <span className="text-xs text-[#666]">{team.player_count || 0} players</span>
        </div>
      </div>
      <button data-testid={`promote-team-${team.id}-btn`}
        onClick={(e) => openPromote(team, e)}
        title="Promote roster to next season"
        className="flex items-center gap-1.5 text-[10px] tracking-[0.15em] uppercase font-bold px-3 py-2 bg-[#10B981]/10 text-[#10B981] hover:bg-[#10B981]/20 transition-colors opacity-0 group-hover:opacity-100">
        <ArrowsClockwise size={12} weight="bold" /> Promote
      </button>
      <button data-testid={`delete-team-${team.id}-btn`}
        onClick={(e) => handleDeleteTeam(e, team.id)}
        className="p-2 text-[#444] hover:text-[#EF4444] hover:bg-[#EF4444]/10 opacity-0 group-hover:opacity-100 transition-all">
        <Trash size={14} />
      </button>
    </div>
  );

  const renderTeamForm = (clubId, color = '#007AFF') => {
    if (teamFormClubId !== clubId) return null;
    return (
      <form onSubmit={handleCreateTeam} data-testid={`team-form-${clubId || 'unaffiliated'}`}
        onClick={(e) => e.stopPropagation()}
        className="bg-[#0A0A0A] border border-white/10 p-4 grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div className="md:col-span-1">
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Team Name *</label>
          <input data-testid="team-name-input" type="text" value={teamForm.name}
            onChange={(e) => setTeamForm({ ...teamForm, name: e.target.value })}
            placeholder="e.g., 2007 B Premier"
            className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2.5 text-sm focus:outline-none focus:border-[#007AFF]" required autoFocus />
        </div>
        <div>
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Season *</label>
          <input data-testid="team-season-input" type="text" value={teamForm.season}
            onChange={(e) => setTeamForm({ ...teamForm, season: e.target.value })}
            placeholder="e.g., 2025/26"
            className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2.5 text-sm focus:outline-none focus:border-[#007AFF]" required />
        </div>
        <div className="flex gap-2">
          <button data-testid="submit-team-btn" type="submit"
            style={{ backgroundColor: color }}
            className="flex-1 hover:opacity-90 text-black py-2.5 font-bold tracking-wider uppercase text-xs transition-opacity">
            Create
          </button>
          <button type="button" onClick={() => setTeamFormClubId(null)}
            className="px-4 py-2.5 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] text-xs font-bold uppercase">
            Cancel
          </button>
        </div>
      </form>
    );
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
          <div className="ml-auto">
            <button data-testid="add-club-btn" onClick={() => { setShowClubForm(true); setEditingClub(null); setClubName(''); }}
              className="flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-5 py-2.5 font-bold tracking-wider uppercase text-xs transition-colors">
              <Plus size={16} weight="bold" /> Add Club
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {/* Club Form */}
        {showClubForm && (
          <form onSubmit={handleSaveClub} data-testid="club-form"
            className="bg-[#141414] border border-white/10 p-6">
            <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-4">
              {editingClub ? 'Edit Club' : 'New Soccer Club'}
            </h3>
            <div className="flex gap-3">
              <input data-testid="club-name-input" type="text" value={clubName}
                onChange={(e) => setClubName(e.target.value)}
                placeholder="e.g., Lakeshore FC" autoFocus
                className="flex-1 bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
              <button data-testid="submit-club-btn" type="submit"
                className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                {editingClub ? 'Save' : 'Create'}
              </button>
              <button type="button" onClick={() => { setShowClubForm(false); setEditingClub(null); }}
                className="px-4 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold uppercase">
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Empty state */}
        {clubs.length === 0 && teams.length === 0 && (
          <div className="text-center py-16 border border-dashed border-white/10">
            <Shield size={56} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-lg text-[#A3A3A3] mb-1">No clubs or teams yet</p>
            <p className="text-xs text-[#666]">Start by adding your soccer club, then nest teams &amp; seasons under it</p>
          </div>
        )}

        {/* Clubs (each with nested teams) */}
        {clubs.map(club => {
          const collapsed = collapsedClubs[club.id];
          const clubTeams = teamsByClub[club.id] || [];
          return (
            <section key={club.id} data-testid={`club-card-${club.id}`}
              className="bg-[#141414] border border-white/10">
              {/* Club Header */}
              <div className="p-5 border-b border-white/5 flex items-center gap-4 group">
                <button onClick={() => toggleClub(club.id)}
                  data-testid={`toggle-club-${club.id}`}
                  className="text-[#A3A3A3] hover:text-white transition-colors">
                  {collapsed ? <CaretRight size={18} weight="bold" /> : <CaretDown size={18} weight="bold" />}
                </button>
                <div className="w-14 h-14 flex-shrink-0 bg-[#0A0A0A] border border-white/10 flex items-center justify-center overflow-hidden relative">
                  {club.logo_url ? (
                    <img src={`${API.replace('/api', '')}${club.logo_url}`} alt={club.name}
                      className="w-full h-full object-contain" />
                  ) : (
                    <Shield size={24} className="text-[#333]" />
                  )}
                  <label data-testid={`upload-logo-${club.id}-btn`}
                    className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer">
                    {uploadingLogo === club.id ? (
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Upload size={14} className="text-white" />
                    )}
                    <input type="file" accept="image/*" className="hidden"
                      onChange={(e) => handleLogoUpload(club.id, e.target.files[0])} />
                  </label>
                </div>
                <div className="flex-1 min-w-0">
                  <h2 className="text-2xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>{club.name}</h2>
                  <p className="text-xs text-[#A3A3A3] mt-0.5">
                    {clubTeams.length} team{clubTeams.length !== 1 ? 's' : ''}
                    {clubTeams.length > 0 && ' • '}
                    {clubTeams.length > 0 && `${clubTeams.reduce((s, t) => s + (t.player_count || 0), 0)} players total`}
                  </p>
                </div>
                <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button data-testid={`add-team-to-${club.id}-btn`}
                    onClick={() => openTeamForm(club.id)}
                    className="flex items-center gap-1.5 text-[10px] tracking-[0.15em] uppercase font-bold px-3 py-2 bg-[#007AFF]/10 text-[#007AFF] hover:bg-[#007AFF]/20 transition-colors">
                    <Plus size={12} weight="bold" /> Team
                  </button>
                  <button data-testid={`edit-club-${club.id}-btn`}
                    onClick={() => { setEditingClub(club); setClubName(club.name); setShowClubForm(true); }}
                    className="p-2 text-[#A3A3A3] hover:text-white hover:bg-white/10 transition-colors">
                    <PencilSimple size={14} />
                  </button>
                  <button data-testid={`delete-club-${club.id}-btn`}
                    onClick={() => handleDeleteClub(club.id)}
                    className="p-2 text-[#A3A3A3] hover:text-[#EF4444] hover:bg-[#EF4444]/10 transition-colors">
                    <Trash size={14} />
                  </button>
                </div>
              </div>

              {/* Nested Teams */}
              {!collapsed && (
                <div className="p-5 space-y-3" data-testid={`teams-of-${club.id}`}>
                  {renderTeamForm(club.id)}
                  {clubTeams.length === 0 && teamFormClubId !== club.id ? (
                    <button data-testid={`empty-add-team-${club.id}`}
                      onClick={() => openTeamForm(club.id)}
                      className="w-full py-6 border border-dashed border-white/10 text-[#A3A3A3] hover:text-white hover:border-[#007AFF]/40 transition-colors flex items-center justify-center gap-2 text-sm">
                      <Plus size={14} /> Add first team to {club.name}
                    </button>
                  ) : (
                    clubTeams.map(renderTeamRow)
                  )}
                </div>
              )}
            </section>
          );
        })}

        {/* Unaffiliated Teams */}
        {teamsByClub._unaffiliated.length > 0 && (
          <section data-testid="unaffiliated-section" className="bg-[#141414] border border-white/10">
            <div className="p-5 border-b border-white/5 flex items-center gap-3">
              <Users size={20} className="text-[#A3A3A3]" />
              <h2 className="text-lg font-bold" style={{ fontFamily: 'Bebas Neue' }}>Unaffiliated Teams</h2>
              <span className="text-[10px] text-[#666] tracking-wider uppercase ml-auto">
                Not under any club
              </span>
            </div>
            <div className="p-5 space-y-3">
              {renderTeamForm('')}
              {teamsByClub._unaffiliated.map(renderTeamRow)}
            </div>
          </section>
        )}

        {/* Add unaffiliated team trigger */}
        {clubs.length === 0 && teamFormClubId !== '' && (
          <button data-testid="add-unaffiliated-team-btn"
            onClick={() => openTeamForm('')}
            className="w-full py-4 border border-dashed border-white/10 text-[#A3A3A3] hover:text-white hover:border-[#007AFF]/40 transition-colors flex items-center justify-center gap-2 text-sm">
            <Plus size={14} /> Create a team without a club
          </button>
        )}
      </main>

      {/* Promote Modal */}
      {promoteTarget && (
        <div data-testid="promote-modal-overlay" onClick={() => !promoting && setPromoteTarget(null)}
          className="fixed inset-0 bg-black/70 z-[100] flex items-center justify-center px-4">
          <form onClick={(e) => e.stopPropagation()} onSubmit={handlePromote}
            className="bg-[#141414] border border-white/10 max-w-lg w-full p-6">
            <div className="flex items-center gap-3 mb-2">
              <ArrowsClockwise size={22} className="text-[#10B981]" weight="bold" />
              <h3 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
                Promote to Next Season
              </h3>
            </div>
            <p className="text-sm text-[#A3A3A3] mb-5">
              Carry <strong className="text-white">{promoteTarget.name}</strong> ({promoteTarget.season})'s
              roster forward into a new team for the next season. Players keep their photos and jersey numbers.
            </p>

            <div className="space-y-3 mb-5">
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">New Season *</label>
                <input data-testid="promote-season-input" type="text"
                  value={promoteForm.new_season}
                  onChange={(e) => setPromoteForm({ ...promoteForm, new_season: e.target.value })}
                  placeholder="e.g., 2026/27"
                  required autoFocus
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none" />
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">New Team Name</label>
                <input data-testid="promote-name-input" type="text"
                  value={promoteForm.new_team_name}
                  onChange={(e) => setPromoteForm({ ...promoteForm, new_team_name: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#10B981] focus:outline-none" />
              </div>
              <label className="flex items-center gap-2 text-sm text-[#A3A3A3] cursor-pointer pt-1">
                <input data-testid="promote-keep-old" type="checkbox"
                  checked={promoteForm.keep_old}
                  onChange={(e) => setPromoteForm({ ...promoteForm, keep_old: e.target.checked })}
                  className="accent-[#10B981]" />
                Also keep players on the old roster (recommended)
              </label>
            </div>

            <div className="flex gap-3">
              <button data-testid="promote-submit-btn" type="submit" disabled={promoting}
                className="flex-1 bg-[#10B981] hover:bg-[#0EA371] disabled:opacity-50 text-black py-3 font-bold tracking-wider uppercase text-xs transition-colors flex items-center justify-center gap-2">
                {promoting ? 'Promoting…' : <><ArrowsClockwise size={14} weight="bold" /> Promote Roster</>}
              </button>
              <button type="button" onClick={() => setPromoteTarget(null)} disabled={promoting}
                className="px-5 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold uppercase">
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

export default ClubManager;
