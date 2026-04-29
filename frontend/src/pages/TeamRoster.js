import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Users, Plus, Trash, Upload, UserCircle, CalendarBlank, Shield, ShareNetwork, Copy, Check, X, UserPlus } from '@phosphor-icons/react';

const TeamRoster = () => {
  const { teamId } = useParams();
  const navigate = useNavigate();
  const [team, setTeam] = useState(null);
  const [players, setPlayers] = useState([]);
  const [clubs, setClubs] = useState([]);
  const [showAddPlayer, setShowAddPlayer] = useState(false);
  const [playerForm, setPlayerForm] = useState({ name: '', number: '', position: '' });
  const [uploadingPic, setUploadingPic] = useState(null);
  const [picVersions, setPicVersions] = useState({});
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showAddExisting, setShowAddExisting] = useState(false);
  const [eligible, setEligible] = useState([]);
  const [eligibleLoading, setEligibleLoading] = useState(false);

  useEffect(() => {
    fetchTeam();
    fetchPlayers();
    fetchClubs();
  }, [teamId]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchTeam = async () => {
    try {
      const res = await axios.get(`${API}/teams/${teamId}`, { headers: getAuthHeader() });
      setTeam(res.data);
    } catch (err) { console.error('Failed to fetch team:', err); }
  };

  const fetchPlayers = async () => {
    try {
      const res = await axios.get(`${API}/teams/${teamId}/players`, { headers: getAuthHeader() });
      setPlayers(res.data);
    } catch (err) { console.error('Failed to fetch players:', err); }
  };

  const fetchClubs = async () => {
    try {
      const res = await axios.get(`${API}/clubs`, { headers: getAuthHeader() });
      setClubs(res.data);
    } catch (err) { console.error('Failed to fetch clubs:', err); }
  };

  const handleAddPlayer = async (e) => {
    e.preventDefault();
    if (!playerForm.name.trim()) return;
    try {
      await axios.post(`${API}/players`, {
        team_id: teamId,
        name: playerForm.name,
        number: playerForm.number ? parseInt(playerForm.number) : null,
        position: playerForm.position,
        team: team?.name || ''
      }, { headers: getAuthHeader() });
      setPlayerForm({ name: '', number: '', position: '' });
      setShowAddPlayer(false);
      fetchPlayers();
    } catch (err) { console.error('Failed to add player:', err); }
  };

  const handleDeletePlayer = async (playerId) => {
    const player = players.find(p => p.id === playerId);
    const otherTeams = (player?.team_ids || []).filter(tid => tid !== teamId);
    const msg = otherTeams.length > 0
      ? `Remove ${player?.name} from this team? They'll stay on their other ${otherTeams.length} team${otherTeams.length === 1 ? '' : 's'}.`
      : `Remove ${player?.name || 'this player'} from the team? Their record will be deleted since this is their only team.`;
    if (!window.confirm(msg)) return;
    try {
      if (otherTeams.length > 0) {
        // Multi-team: just unlink from this team
        await axios.delete(`${API}/players/${playerId}/teams/${teamId}`, { headers: getAuthHeader() });
      } else {
        // Last team: hard delete
        await axios.delete(`${API}/players/${playerId}`, { headers: getAuthHeader() });
      }
      setPlayers(players.filter(p => p.id !== playerId));
    } catch (err) { console.error('Failed to delete player:', err); }
  };

  const handleToggleShare = async () => {
    try {
      const res = await axios.post(`${API}/teams/${teamId}/share`, {}, { headers: getAuthHeader() });
      setTeam(prev => ({ ...prev, share_token: res.data.share_token }));
    } catch (err) {
      alert('Failed to update share status: ' + (err.response?.data?.detail || err.message));
    }
  };

  const shareUrl = useMemo(() =>
    team?.share_token ? `${window.location.origin}/api/og/team/${team.share_token}` : '',
    [team?.share_token]
  );

  const previewUrl = useMemo(() =>
    team?.share_token ? `${window.location.origin}/shared-team/${team.share_token}` : '',
    [team?.share_token]
  );

  const handleCopyShare = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      // Fallback for sandboxed iframes
      const ta = document.createElement('textarea');
      ta.value = shareUrl; document.body.appendChild(ta);
      ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleProfilePicUpload = async (playerId, file) => {
    if (!file) return;
    setUploadingPic(playerId);
    try {
      const formData = new FormData();
      formData.append('file', file);
      await axios.post(`${API}/players/${playerId}/profile-pic`, formData, { headers: getAuthHeader() });
      setPicVersions(prev => ({ ...prev, [playerId]: Date.now() }));
      fetchPlayers();
    } catch (err) {
      alert('Failed to upload photo: ' + (err.response?.data?.detail || err.message));
    } finally {
      setUploadingPic(null);
    }
  };

  const openAddExisting = async () => {
    setShowAddExisting(true);
    setEligibleLoading(true);
    try {
      const res = await axios.get(`${API}/teams/${teamId}/eligible-players`, { headers: getAuthHeader() });
      setEligible(res.data);
    } catch (err) {
      console.error('Failed to load eligible players:', err);
      setEligible([]);
    } finally {
      setEligibleLoading(false);
    }
  };

  const handleAddExisting = async (playerId) => {
    try {
      await axios.post(`${API}/players/${playerId}/teams/${teamId}`, {}, { headers: getAuthHeader() });
      setEligible(prev => prev.filter(p => p.id !== playerId));
      fetchPlayers();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to add player to team');
    }
  };

  const sortedPlayers = useMemo(() =>
    [...players].sort((a, b) => (a.number || 99) - (b.number || 99)),
    [players]
  );

  const clubInfo = useMemo(() =>
    clubs.find(c => c.id === team?.club),
    [clubs, team?.club]
  );

  const positionGroups = useMemo(() => {
    const groups = { Goalkeeper: [], Defender: [], Midfielder: [], Forward: [], Other: [] };
    for (const p of sortedPlayers) {
      const pos = p.position || 'Other';
      if (groups[pos]) groups[pos].push(p);
      else groups.Other.push(p);
    }
    return Object.entries(groups).filter(([, list]) => list.length > 0);
  }, [sortedPlayers]);

  if (!team) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <button data-testid="back-btn" onClick={() => navigate('/clubs')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} />
          </button>
          <div className="flex items-center gap-3">
            {clubInfo?.logo_url ? (
              <img src={`${API.replace('/api', '')}${clubInfo.logo_url}`} alt="" className="w-8 h-8 object-contain" />
            ) : (
              <Shield size={24} className="text-[#333]" />
            )}
            <div>
              <h1 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>{team.name}</h1>
              <div className="flex items-center gap-2 text-xs text-[#A3A3A3]">
                <CalendarBlank size={12} /> {team.season}
                {clubInfo && <span className="text-[#007AFF]">— {clubInfo.name}</span>}
              </div>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs text-[#666] bg-white/5 px-3 py-1.5">{players.length} Players</span>
            <button data-testid="share-team-btn" onClick={() => setShareModalOpen(true)}
              className={`flex items-center gap-2 px-4 py-2 font-bold tracking-wider uppercase text-xs transition-colors border ${
                team.share_token
                  ? 'border-[#10B981]/40 text-[#10B981] hover:bg-[#10B981]/10'
                  : 'border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F]'
              }`}>
              <ShareNetwork size={14} weight="bold" /> {team.share_token ? 'Shared' : 'Share'}
            </button>
            <button data-testid="add-existing-player-btn" onClick={openAddExisting}
              className="flex items-center gap-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-4 py-2 font-bold tracking-wider uppercase text-xs transition-colors">
              <UserPlus size={14} weight="bold" /> Add Existing
            </button>
            <button data-testid="add-player-btn" onClick={() => setShowAddPlayer(true)}
              className="flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-4 py-2 font-bold tracking-wider uppercase text-xs transition-colors">
              <Plus size={14} weight="bold" /> Add Player
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Add Player Form */}
        {showAddPlayer && (
          <form onSubmit={handleAddPlayer} data-testid="add-player-form"
            className="bg-[#141414] border border-white/10 p-6 mb-8">
            <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-4">Register New Player</h3>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Name *</label>
                <input data-testid="player-name-input" type="text" value={playerForm.name}
                  onChange={(e) => setPlayerForm({ ...playerForm, name: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Jersey Number</label>
                <input data-testid="player-number-input" type="number" value={playerForm.number}
                  onChange={(e) => setPlayerForm({ ...playerForm, number: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" />
              </div>
              <div>
                <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Position</label>
                <select data-testid="player-position-select" value={playerForm.position}
                  onChange={(e) => setPlayerForm({ ...playerForm, position: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none">
                  <option value="">Select...</option>
                  <option value="Goalkeeper">Goalkeeper</option>
                  <option value="Defender">Defender</option>
                  <option value="Midfielder">Midfielder</option>
                  <option value="Forward">Forward</option>
                </select>
              </div>
              <div className="flex gap-2">
                <button data-testid="submit-player-btn" type="submit"
                  className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                  Add
                </button>
                <button type="button" onClick={() => setShowAddPlayer(false)}
                  className="px-4 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs">
                  Cancel
                </button>
              </div>
            </div>
          </form>
        )}

        {/* Player Roster */}
        {players.length === 0 ? (
          <div className="text-center py-20 border border-dashed border-white/10">
            <Users size={64} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-xl text-[#A3A3A3] mb-2">No players registered</p>
            <p className="text-sm text-[#666]">Add players to build your team roster</p>
          </div>
        ) : (
          <div className="space-y-8">
            {positionGroups.map(([position, groupPlayers]) => (
              <section key={position}>
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-1 h-5 bg-[#007AFF]" />
                  <h2 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">
                    {position}s ({groupPlayers.length})
                  </h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {groupPlayers.map(player => (
                    <div key={player.id} data-testid={`roster-player-${player.id}`}
                      className="bg-[#141414] border border-white/10 p-4 flex items-center gap-4 group hover:bg-[#1A1A1A] transition-colors">
                      {/* Profile Pic */}
                      <div className="w-14 h-14 flex-shrink-0 rounded-full bg-[#0A0A0A] border border-white/10 overflow-hidden relative flex items-center justify-center">
                        {player.profile_pic_url ? (
                          <img src={`${API.replace('/api', '')}${player.profile_pic_url}?v=${picVersions[player.id] || player.id}`} alt={player.name}
                            className="w-full h-full object-cover" />
                        ) : (
                          <UserCircle size={32} className="text-[#333]" />
                        )}
                        <label data-testid={`upload-pic-${player.id}`}
                          className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer rounded-full">
                          {uploadingPic === player.id ? (
                            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          ) : (
                            <Upload size={16} className="text-white" />
                          )}
                          <input type="file" accept="image/*" className="hidden"
                            onChange={(e) => handleProfilePicUpload(player.id, e.target.files[0])} />
                        </label>
                      </div>
                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-2xl font-bold text-[#007AFF]" style={{ fontFamily: 'Bebas Neue' }}>
                            {player.number || '—'}
                          </span>
                          <h3 className="text-base font-semibold text-white truncate">{player.name}</h3>
                        </div>
                        <p className="text-xs text-[#666] mt-0.5">{player.position || 'No position'}</p>
                      </div>
                      {/* Delete */}
                      <button data-testid={`delete-player-${player.id}`}
                        onClick={() => handleDeletePlayer(player.id)}
                        className="p-2 text-[#444] hover:text-[#EF4444] hover:bg-[#EF4444]/10 transition-colors opacity-0 group-hover:opacity-100">
                        <Trash size={16} />
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </main>

      {/* Add Existing Player Modal */}
      {showAddExisting && (
        <div data-testid="existing-modal-overlay" onClick={() => setShowAddExisting(false)}
          className="fixed inset-0 bg-black/70 z-[100] flex items-center justify-center px-4">
          <div onClick={(e) => e.stopPropagation()}
            className="bg-[#141414] border border-white/10 max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="p-6 border-b border-white/10 flex items-start justify-between">
              <div>
                <h3 className="text-xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
                  Add Existing Player
                </h3>
                <p className="text-xs text-[#A3A3A3] mt-1">
                  Players already registered on a different team in season <strong className="text-white">{team?.season}</strong>.
                  Each player can be on at most 2 teams per season.
                </p>
              </div>
              <button data-testid="close-existing-modal" onClick={() => setShowAddExisting(false)}
                className="p-1 text-[#666] hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="p-6 overflow-y-auto">
              {eligibleLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="w-6 h-6 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
                </div>
              ) : eligible.length === 0 ? (
                <div className="text-center py-10">
                  <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
                  <p className="text-[#A3A3A3]">No eligible players</p>
                  <p className="text-xs text-[#666] mt-1">
                    No other teams exist in {team?.season}, or all candidates are already on this team.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {eligible.map(p => (
                    <div key={p.id} data-testid={`eligible-${p.id}`}
                      className="bg-[#0A0A0A] border border-white/10 p-3 flex items-center gap-3">
                      <div className="w-12 h-12 flex-shrink-0 rounded-full bg-[#141414] border border-white/10 overflow-hidden flex items-center justify-center">
                        {p.profile_pic_url ? (
                          <img src={`${API.replace('/api', '')}${p.profile_pic_url}`} alt={p.name}
                            className="w-full h-full object-cover" />
                        ) : (
                          <UserCircle size={28} className="text-[#333]" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-lg font-bold text-[#007AFF]" style={{ fontFamily: 'Bebas Neue' }}>
                            {p.number ?? '—'}
                          </span>
                          <span className="text-sm font-semibold text-white truncate">{p.name}</span>
                        </div>
                        <div className="text-[10px] text-[#666] mt-0.5 tracking-wider">
                          {p.position || 'No position'}
                          {p.other_team_names?.length > 0 && (
                            <> • Already on: {p.other_team_names.join(', ')}</>
                          )}
                        </div>
                      </div>
                      <button data-testid={`add-existing-${p.id}-btn`}
                        disabled={p.at_cap}
                        onClick={() => handleAddExisting(p.id)}
                        className={`text-xs px-3 py-2 font-bold tracking-wider uppercase transition-colors ${
                          p.at_cap
                            ? 'bg-[#333] text-[#666] cursor-not-allowed'
                            : 'bg-[#007AFF] hover:bg-[#005bb5] text-white'
                        }`}>
                        {p.at_cap ? 'At cap' : 'Add'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Share Modal */}
      {shareModalOpen && (
        <div data-testid="share-modal-overlay" onClick={() => setShareModalOpen(false)}
          className="fixed inset-0 bg-black/70 z-[100] flex items-center justify-center px-4">
          <div onClick={(e) => e.stopPropagation()}
            className="bg-[#141414] border border-white/10 max-w-lg w-full p-6">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
                  Public Team Page
                </h3>
                <p className="text-xs text-[#A3A3A3] mt-1">Share your roster with parents, scouts, and recruiters.</p>
              </div>
              <button data-testid="close-share-modal" onClick={() => setShareModalOpen(false)}
                className="p-1 text-[#666] hover:text-white">
                <X size={20} />
              </button>
            </div>

            {team.share_token ? (
              <>
                <div className="bg-[#0A0A0A] border border-white/10 p-3 flex items-center gap-2 mb-3">
                  <input data-testid="share-url-input" readOnly value={shareUrl}
                    className="flex-1 bg-transparent text-xs text-[#A3A3A3] outline-none truncate" />
                  <button data-testid="copy-share-btn" onClick={handleCopyShare}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-[#007AFF] hover:bg-[#005bb5] text-white tracking-wider uppercase font-bold">
                    {copied ? <><Check size={12} weight="bold" /> Copied</> : <><Copy size={12} weight="bold" /> Copy</>}
                  </button>
                </div>
                <div className="text-[10px] text-[#10B981] tracking-[0.15em] uppercase font-bold mb-3 flex items-center gap-1.5">
                  <Check size={11} weight="bold" /> Smart link — unfurls with team name & crest in WhatsApp, Slack, Twitter
                </div>
                <a data-testid="preview-link" href={previewUrl} target="_blank" rel="noopener noreferrer"
                  className="block text-xs text-[#A3A3A3] hover:text-white underline underline-offset-2 mb-4">
                  Open public page in new tab →
                </a>
                <p className="text-[11px] text-[#666] mb-4">
                  Anyone with this link can see the squad photos, jersey numbers, positions, and any public
                  match film folders you've shared from this account.
                </p>
                <button data-testid="revoke-share-btn" onClick={handleToggleShare}
                  className="w-full text-xs py-3 border border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10 tracking-wider uppercase font-bold transition-colors">
                  Revoke Public Link
                </button>
              </>
            ) : (
              <>
                <div className="bg-[#0A0A0A] border border-white/10 p-4 mb-4">
                  <p className="text-sm text-[#A3A3A3] leading-relaxed">
                    Generate a public link that lets anyone see the team's squad list (with photos & jersey numbers)
                    and any match film folders you've already shared. No login required for viewers.
                  </p>
                </div>
                <button data-testid="enable-share-btn" onClick={handleToggleShare}
                  className="w-full text-xs py-3 bg-[#007AFF] hover:bg-[#005bb5] text-white tracking-wider uppercase font-bold transition-colors flex items-center justify-center gap-2">
                  <ShareNetwork size={14} weight="bold" /> Generate Public Link
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default TeamRoster;
