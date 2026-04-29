import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import { Play, Plus, SignOut, VideoCamera, CalendarBlank, Trophy, FolderSimple, FolderOpen, Lock, LockOpen, DotsThreeVertical, PencilSimple, Trash, CaretRight, CaretDown, ShareNetwork, Copy, Check, Shield, ChartLineUp, Globe } from '@phosphor-icons/react';
import CoachPulseCard from './components/CoachPulseCard';

const Dashboard = () => {
  const [matches, setMatches] = useState([]);
  const [folders, setFolders] = useState([]);
  const [selectedFolderId, setSelectedFolderId] = useState(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [sharingFolder, setSharingFolder] = useState(null);
  const [copied, setCopied] = useState(false);
  const [editingFolder, setEditingFolder] = useState(null);
  const [folderMenuId, setFolderMenuId] = useState(null);
  const [expandedFolders, setExpandedFolders] = useState({});
  const [formData, setFormData] = useState({ team_home: '', team_away: '', date: '', competition: '' });
  const [folderFormData, setFolderFormData] = useState({ name: '', parent_id: null, is_private: false });
  const [loading, setLoading] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedMatchIds, setSelectedMatchIds] = useState([]);
  const [bulkBusy, setBulkBusy] = useState(false);

  const toggleMatchSelection = (id) => {
    setSelectedMatchIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const exitSelectionMode = () => { setSelectionMode(false); setSelectedMatchIds([]); };

  const bulkMove = async (folder_id) => {
    if (selectedMatchIds.length === 0) return;
    setBulkBusy(true);
    try {
      await axios.post(`${API}/matches/bulk/move`, { match_ids: selectedMatchIds, folder_id }, { headers: getAuthHeader() });
      await fetchMatches();
      exitSelectionMode();
    } catch (err) {
      alert('Bulk move failed: ' + (err.response?.data?.detail || err.message));
    } finally { setBulkBusy(false); }
  };

  const bulkSetCompetition = async () => {
    const comp = window.prompt('Set competition for ' + selectedMatchIds.length + ' selected match' + (selectedMatchIds.length === 1 ? '' : 'es') + ':', '');
    if (comp === null) return;
    setBulkBusy(true);
    try {
      await axios.post(`${API}/matches/bulk/competition`, { match_ids: selectedMatchIds, competition: comp }, { headers: getAuthHeader() });
      await fetchMatches();
      exitSelectionMode();
    } catch (err) {
      alert('Bulk update failed: ' + (err.response?.data?.detail || err.message));
    } finally { setBulkBusy(false); }
  };

  const bulkDelete = async () => {
    if (!window.confirm(`Delete ${selectedMatchIds.length} match${selectedMatchIds.length === 1 ? '' : 'es'}? Their videos enter the 24h restore window. Clips and AI analyses are removed permanently.`)) return;
    setBulkBusy(true);
    try {
      await axios.post(`${API}/matches/bulk/delete`, { match_ids: selectedMatchIds }, { headers: getAuthHeader() });
      await fetchMatches();
      exitSelectionMode();
    } catch (err) {
      alert('Bulk delete failed: ' + (err.response?.data?.detail || err.message));
    } finally { setBulkBusy(false); }
  };
  const navigate = useNavigate();
  const user = getCurrentUser();

  useEffect(() => { fetchMatches(); fetchFolders(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchMatches = async () => {
    try {
      const response = await axios.get(`${API}/matches`, { headers: getAuthHeader() });
      setMatches(response.data);
    } catch (err) { console.error('Failed to fetch matches:', err); }
  };

  const fetchFolders = async () => {
    try {
      const response = await axios.get(`${API}/folders`, { headers: getAuthHeader() });
      setFolders(response.data);
      // Auto-expand all folders on first load
      const expanded = {};
      response.data.forEach(f => { expanded[f.id] = true; });
      setExpandedFolders(prev => ({ ...expanded, ...prev }));
    } catch (err) { console.error('Failed to fetch folders:', err); }
  };

  const handleCreateMatch = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const payload = { ...formData };
      if (selectedFolderId && selectedFolderId !== '__none__') payload.folder_id = selectedFolderId;
      await axios.post(`${API}/matches`, payload, { headers: getAuthHeader() });
      setShowCreateModal(false);
      setFormData({ team_home: '', team_away: '', date: '', competition: '' });
      fetchMatches();
    } catch (err) { console.error('Failed to create match:', err); }
    finally { setLoading(false); }
  };

  const handleCreateFolder = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...folderFormData };
      if (!payload.parent_id) delete payload.parent_id;
      if (editingFolder) {
        await axios.patch(`${API}/folders/${editingFolder.id}`, payload, { headers: getAuthHeader() });
      } else {
        if (selectedFolderId && selectedFolderId !== '__none__' && !payload.parent_id) payload.parent_id = selectedFolderId;
        await axios.post(`${API}/folders`, payload, { headers: getAuthHeader() });
      }
      setShowFolderModal(false);
      setEditingFolder(null);
      setFolderFormData({ name: '', parent_id: null, is_private: false });
      fetchFolders();
    } catch (err) { console.error('Failed to save folder:', err); }
  };

  const handleDeleteFolder = async (folderId) => {
    if (!window.confirm('Delete this folder? Matches will move to parent.')) return;
    try {
      await axios.delete(`${API}/folders/${folderId}`, { headers: getAuthHeader() });
      if (selectedFolderId === folderId) setSelectedFolderId(null);
      fetchFolders();
      fetchMatches();
    } catch (err) { console.error('Failed to delete folder:', err); }
  };

  const handleMoveMatch = async (matchId, folderId) => {
    try {
      await axios.patch(`${API}/matches/${matchId}`, { folder_id: folderId || null }, { headers: getAuthHeader() });
      fetchMatches();
    } catch (err) { console.error('Failed to move match:', err); }
  };

  const handleToggleShare = async (folder) => {
    // If already shared, just open the modal to show link / allow revoke
    if (folder.share_token) {
      setSharingFolder(folder);
      setShowShareModal(true);
      return;
    }
    // Otherwise generate a new share token
    try {
      const res = await axios.post(`${API}/folders/${folder.id}/share`, {}, { headers: getAuthHeader() });
      setFolders(prev => prev.map(f => f.id === folder.id ? { ...f, share_token: res.data.share_token } : f));
      const updated = { ...folder, share_token: res.data.share_token };
      setSharingFolder(updated);
      setShowShareModal(true);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to share folder');
    }
  };

  const handleRevokeShare = async () => {
    if (!sharingFolder) return;
    try {
      await axios.post(`${API}/folders/${sharingFolder.id}/share`, {}, { headers: getAuthHeader() });
      setFolders(prev => prev.map(f => f.id === sharingFolder.id ? { ...f, share_token: null } : f));
      setSharingFolder({ ...sharingFolder, share_token: null });
      setShowShareModal(false);
    } catch (err) {
      alert('Failed to revoke share link');
    }
  };

  const copyShareLink = () => {
    const url = `${window.location.origin}/api/og/folder/${sharingFolder.share_token}`;
    try {
      navigator.clipboard.writeText(url).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }).catch(() => {
        fallbackCopy(url);
      });
    } catch {
      fallbackCopy(url);
    }
  };

  const fallbackCopy = (text) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      alert('Copy failed — please select and copy the link manually.');
    }
    document.body.removeChild(ta);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    navigate('/auth');
  };

  const toggleFolderExpand = (folderId) => {
    setExpandedFolders(prev => ({ ...prev, [folderId]: !prev[folderId] }));
  };

  // Build a flat list of folder items with depth for rendering
  const flatFolderList = useMemo(() => {
    const result = [];
    const addChildren = (parentId, depth) => {
      const children = folders.filter(f => (f.parent_id || null) === parentId).sort((a, b) => a.name.localeCompare(b.name));
      for (const folder of children) {
        const hasChildren = folders.some(f => f.parent_id === folder.id);
        const isExpanded = expandedFolders[folder.id] !== false;
        result.push({ ...folder, depth, hasChildren, isExpanded });
        if (hasChildren && isExpanded) {
          addChildren(folder.id, depth + 1);
        }
      }
    };
    addChildren(null, 0);
    return result;
  }, [folders, expandedFolders]);

  const unfolderedCount = matches.filter(m => !m.folder_id).length;
  const displayMatches = selectedFolderId === '__none__'
    ? matches.filter(m => !m.folder_id)
    : selectedFolderId
    ? matches.filter(m => m.folder_id === selectedFolderId)
    : matches;

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Play size={32} weight="fill" className="text-[#007AFF]" />
            <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>SOCCER SCOUT</h1>
          </div>
          <div className="flex items-center gap-6">
            <button data-testid="clubs-nav-btn" onClick={() => navigate('/clubs')}
              className="flex items-center gap-2 px-3 py-1.5 text-xs text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors border border-white/10 font-bold uppercase tracking-wider">
              <Shield size={16} /> Clubs & Teams
            </button>
            <button data-testid="coach-network-nav-btn" onClick={() => navigate('/coach-network')}
              className="flex items-center gap-2 px-3 py-1.5 text-xs text-[#A855F7] hover:text-white hover:bg-[#A855F7]/15 transition-colors border border-[#A855F7]/30 font-bold uppercase tracking-wider">
              <Globe size={16} weight="bold" /> Coach Network
            </button>
            <div className="text-right">
              <p className="text-sm text-[#A3A3A3]">{user?.name}</p>
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{user?.role}</p>
            </div>
            <button data-testid="logout-btn" onClick={handleLogout}
              className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
              <SignOut size={24} className="text-[#A3A3A3]" />
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-8 flex gap-6">
        {/* Folder Sidebar */}
        <aside className="w-64 flex-shrink-0" data-testid="folder-sidebar">
          <div className="bg-[#141414] border border-white/10 p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">Folders</h3>
              <button data-testid="create-folder-btn"
                onClick={() => { setEditingFolder(null); setFolderFormData({ name: '', parent_id: (selectedFolderId && selectedFolderId !== '__none__') ? selectedFolderId : null, is_private: false }); setShowFolderModal(true); }}
                className="p-1 hover:bg-[#1F1F1F] transition-colors text-[#007AFF]">
                <Plus size={18} weight="bold" />
              </button>
            </div>

            <button data-testid="all-matches-folder-btn" onClick={() => setSelectedFolderId(null)}
              className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors mb-1 ${
                selectedFolderId === null ? 'bg-[#007AFF]/10 text-[#007AFF] border-l-2 border-[#007AFF]' : 'text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
              }`}>
              <FolderOpen size={18} />
              <span className="flex-1 truncate">All Matches</span>
              <span className="text-[10px] opacity-60">{matches.length}</span>
            </button>

            <button data-testid="unfoldered-matches-btn" onClick={() => setSelectedFolderId('__none__')}
              className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors mb-2 ${
                selectedFolderId === '__none__' ? 'bg-[#007AFF]/10 text-[#007AFF] border-l-2 border-[#007AFF]' : 'text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
              }`}>
              <VideoCamera size={18} />
              <span className="flex-1 truncate">Unsorted</span>
              <span className="text-[10px] opacity-60">{unfolderedCount}</span>
            </button>

            <div className="border-t border-white/5 pt-2">
              {flatFolderList.map(folder => {
                const matchCount = matches.filter(m => m.folder_id === folder.id).length;
                const isSelected = selectedFolderId === folder.id;
                return (
                  <div key={folder.id} style={{ paddingLeft: `${folder.depth * 12}px` }}>
                    <div data-testid={`folder-item-${folder.id}`}
                      className={`flex items-center gap-1 px-2 py-1.5 text-sm transition-colors group relative cursor-pointer ${
                        isSelected ? 'bg-[#007AFF]/10 text-[#007AFF]' : 'text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
                      }`}>
                      {folder.hasChildren ? (
                        <button onClick={(e) => { e.stopPropagation(); toggleFolderExpand(folder.id); }}
                          className="p-0.5 hover:bg-white/10 transition-colors flex-shrink-0">
                          {folder.isExpanded ? <CaretDown size={12} /> : <CaretRight size={12} />}
                        </button>
                      ) : <div className="w-4" />}
                      <button className="flex-1 flex items-center gap-2 min-w-0 text-left"
                        onClick={() => setSelectedFolderId(folder.id)}>
                        <FolderSimple size={16} className="flex-shrink-0" />
                        <span className="truncate text-xs">{folder.name}</span>
                        {folder.is_private && <Lock size={10} className="text-[#EF4444] flex-shrink-0" />}
                        {folder.share_token && <ShareNetwork size={10} className="text-[#4ADE80] flex-shrink-0" />}
                        <span className="text-[10px] opacity-50 ml-auto flex-shrink-0">{matchCount}</span>
                      </button>
                      <button data-testid={`folder-menu-${folder.id}-btn`}
                        onClick={(e) => { e.stopPropagation(); setFolderMenuId(folderMenuId === folder.id ? null : folder.id); }}
                        className="p-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 hover:bg-white/10">
                        <DotsThreeVertical size={14} />
                      </button>
                      {folderMenuId === folder.id && (
                        <div className="absolute right-0 top-full z-50 bg-[#1F1F1F] border border-white/10 py-1 min-w-[120px] shadow-xl"
                          onClick={(e) => e.stopPropagation()}>
                          <button data-testid={`edit-folder-${folder.id}-btn`}
                            onClick={() => { setEditingFolder(folder); setFolderFormData({ name: folder.name, parent_id: folder.parent_id, is_private: folder.is_private }); setShowFolderModal(true); setFolderMenuId(null); }}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[#A3A3A3] hover:bg-white/5 hover:text-white">
                            <PencilSimple size={12} /> Rename
                          </button>
                          {!folder.is_private && (
                            <button data-testid={`share-folder-${folder.id}-btn`}
                              onClick={() => { handleToggleShare(folder); setFolderMenuId(null); }}
                              className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-white/5 ${
                                folder.share_token ? 'text-[#4ADE80]' : 'text-[#A3A3A3] hover:text-white'
                              }`}>
                              <ShareNetwork size={12} /> {folder.share_token ? 'Sharing On' : 'Share'}
                            </button>
                          )}
                          <button data-testid={`folder-trends-${folder.id}-btn`}
                            onClick={() => { navigate(`/folder/${folder.id}/trends`); setFolderMenuId(null); }}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[#A855F7] hover:bg-[#A855F7]/10">
                            <ChartLineUp size={12} /> Season Trends
                          </button>
                          <button data-testid={`delete-folder-${folder.id}-btn`}
                            onClick={() => { handleDeleteFolder(folder.id); setFolderMenuId(null); }}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[#EF4444] hover:bg-[#EF4444]/10">
                            <Trash size={12} /> Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h2 className="text-4xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                {selectedFolderId === '__none__' ? 'Unsorted Matches' :
                 selectedFolderId ? (folders.find(f => f.id === selectedFolderId)?.name || 'Folder') :
                 'Match Library'}
              </h2>
              <p className="text-[#A3A3A3] tracking-wide">{displayMatches.length} match{displayMatches.length !== 1 ? 'es' : ''}</p>
            </div>
            {selectedFolderId && selectedFolderId !== '__none__' && (
              <button data-testid="folder-trends-cta-btn" onClick={() => navigate(`/folder/${selectedFolderId}/trends`)}
                className="flex items-center gap-2 bg-gradient-to-r from-[#A855F7] to-[#FBBF24] hover:opacity-90 text-black px-5 py-3 font-bold tracking-wider uppercase text-xs transition-opacity">
                <ChartLineUp size={14} weight="bold" /> Season Trends
              </button>
            )}
            <button data-testid="create-match-btn" onClick={() => setShowCreateModal(true)}
              className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors flex items-center gap-2">
              <Plus size={24} weight="bold" /> New Match
            </button>
            <button data-testid="toggle-selection-mode-btn"
              onClick={() => selectionMode ? exitSelectionMode() : setSelectionMode(true)}
              className={`px-4 py-3 font-bold tracking-wider uppercase text-xs transition-colors border ${
                selectionMode ? 'border-[#FBBF24] text-[#FBBF24] bg-[#FBBF24]/10' : 'border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F]'
              }`}>
              {selectionMode ? 'Done' : 'Select'}
            </button>
          </div>

          {/* Coach Network CTA Card — appears when not in selection mode */}
          {!selectionMode && (
            <>
              <CoachPulseCard />
              <button data-testid="coach-network-cta-card" onClick={() => navigate('/coach-network')}
              className="w-full mb-6 group flex items-center gap-4 bg-gradient-to-r from-[#1B0F2E] via-[#0F1A2E] to-[#0A0A0A] border border-[#A855F7]/30 hover:border-[#A855F7]/60 hover:from-[#2A1547] transition-all px-5 py-4 text-left">
              <div className="w-12 h-12 bg-[#A855F7]/15 border border-[#A855F7]/30 flex items-center justify-center flex-shrink-0">
                <Globe size={24} weight="bold" className="text-[#A855F7]" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7] mb-1">Coach Network</div>
                <div className="text-base font-bold text-white truncate">See how your coaching stacks up — anonymized</div>
                <div className="text-xs text-[#A3A3A3] mt-0.5 truncate">Platform benchmarks · player position trends · recruiter-level distribution</div>
              </div>
              <CaretRight size={20} className="text-[#A855F7] group-hover:translate-x-1 transition-transform flex-shrink-0" />
            </button>
            </>
          )}

          {/* Bulk action bar */}
          {selectionMode && (
            <div data-testid="bulk-action-bar"
              className="sticky top-0 z-30 bg-[#FBBF24]/15 border border-[#FBBF24]/30 px-4 py-3 flex items-center gap-3 mb-4 -mx-4 md:mx-0 backdrop-blur">
              <span className="text-sm font-bold tracking-wider uppercase text-[#FBBF24]">
                {selectedMatchIds.length} selected
              </span>
              <div className="ml-auto flex flex-wrap gap-2">
                <select data-testid="bulk-move-select"
                  disabled={selectedMatchIds.length === 0 || bulkBusy}
                  onChange={(e) => { if (e.target.value !== '__none__') bulkMove(e.target.value === '' ? null : e.target.value); e.target.value = '__none__'; }}
                  defaultValue="__none__"
                  className="bg-[#0A0A0A] border border-white/10 text-xs text-[#A3A3A3] px-3 py-2 focus:outline-none">
                  <option value="__none__" disabled>Move to folder…</option>
                  <option value="">No folder (root)</option>
                  {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
                <button data-testid="bulk-set-competition-btn" onClick={bulkSetCompetition}
                  disabled={selectedMatchIds.length === 0 || bulkBusy}
                  className="text-xs px-3 py-2 bg-[#007AFF]/15 text-[#007AFF] hover:bg-[#007AFF]/25 disabled:opacity-50 font-bold tracking-wider uppercase">
                  Set Competition
                </button>
                <button data-testid="bulk-delete-btn" onClick={bulkDelete}
                  disabled={selectedMatchIds.length === 0 || bulkBusy}
                  className="text-xs px-3 py-2 bg-[#EF4444]/15 text-[#EF4444] hover:bg-[#EF4444]/25 disabled:opacity-50 font-bold tracking-wider uppercase">
                  Delete
                </button>
              </div>
            </div>
          )}

          {displayMatches.length === 0 ? (
            <div className="text-center py-20">
              <VideoCamera size={80} className="text-[#A3A3A3] mx-auto mb-4" />
              <p className="text-xl text-[#A3A3A3] mb-2">No matches here</p>
              <p className="text-sm text-[#A3A3A3]">Create a match or move one into this folder</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {displayMatches.map((match) => (
                <div key={match.id} data-testid={`match-card-${match.id}`}
                  className={`bg-[#141414] border p-6 hover:bg-[#1F1F1F] transition-colors cursor-pointer group relative ${
                    selectionMode && selectedMatchIds.includes(match.id) ? 'border-[#FBBF24]' : 'border-white/10'
                  }`}
                  onClick={() => selectionMode ? toggleMatchSelection(match.id) : navigate(`/match/${match.id}`)}>
                  {selectionMode && (
                    <div data-testid={`select-${match.id}`}
                      className={`absolute top-3 left-3 w-6 h-6 rounded border-2 flex items-center justify-center ${
                        selectedMatchIds.includes(match.id) ? 'bg-[#FBBF24] border-[#FBBF24]' : 'bg-transparent border-white/30'
                      }`}>
                      {selectedMatchIds.includes(match.id) && (
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                      )}
                    </div>
                  )}
                  {!selectionMode && folders.length > 0 && (
                    <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={(e) => e.stopPropagation()}>
                      <select data-testid={`move-match-${match.id}-select`}
                        value={match.folder_id || ''}
                        onChange={(e) => handleMoveMatch(match.id, e.target.value || null)}
                        className="bg-[#0A0A0A] border border-white/10 text-[10px] text-[#A3A3A3] px-2 py-1 focus:outline-none focus:border-[#007AFF]">
                        <option value="">No folder</option>
                        {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
                      </select>
                    </div>
                  )}
                  <div className="flex items-center gap-2 mb-4">
                    <Trophy size={20} className="text-[#007AFF]" />
                    <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{match.competition || 'Friendly'}</p>
                  </div>
                  <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                    {match.team_home} vs {match.team_away}
                  </h3>
                  <div className="flex items-center gap-2 text-sm text-[#A3A3A3]">
                    <CalendarBlank size={16} />
                    <span>{new Date(match.date + 'T00:00:00').toLocaleDateString()}</span>
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
      </div>

      {/* Create Match Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-6 z-50">
          <div className="bg-[#141414] border border-white/10 w-full max-w-lg p-8">
            <h3 className="text-3xl font-bold mb-6" style={{ fontFamily: 'Bebas Neue' }}>Create New Match</h3>
            <form onSubmit={handleCreateMatch} className="space-y-4">
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Home Team</label>
                <input data-testid="home-team-input" type="text" value={formData.team_home}
                  onChange={(e) => setFormData({ ...formData, team_home: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Away Team</label>
                <input data-testid="away-team-input" type="text" value={formData.team_away}
                  onChange={(e) => setFormData({ ...formData, team_away: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Date</label>
                <input data-testid="match-date-input" type="date" value={formData.date}
                  onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Competition</label>
                <input data-testid="competition-input" type="text" value={formData.competition}
                  onChange={(e) => setFormData({ ...formData, competition: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  placeholder="e.g., Premier League, Champions League" />
              </div>
              <div className="flex gap-4 mt-6">
                <button data-testid="cancel-create-btn" type="button" onClick={() => setShowCreateModal(false)}
                  className="flex-1 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
                  Cancel
                </button>
                <button data-testid="submit-create-btn" type="submit" disabled={loading}
                  className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
                  {loading ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Folder Create/Edit Modal */}
      {showFolderModal && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-6 z-50">
          <div className="bg-[#141414] border border-white/10 w-full max-w-md p-8">
            <h3 className="text-3xl font-bold mb-6" style={{ fontFamily: 'Bebas Neue' }}>
              {editingFolder ? 'Edit Folder' : 'New Folder'}
            </h3>
            <form onSubmit={handleCreateFolder} className="space-y-4">
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Folder Name</label>
                <input data-testid="folder-name-input" type="text" value={folderFormData.name}
                  onChange={(e) => setFolderFormData({ ...folderFormData, name: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  placeholder="e.g., Season 2025-26" required />
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Parent Folder</label>
                <select data-testid="folder-parent-select"
                  value={folderFormData.parent_id || ''}
                  onChange={(e) => setFolderFormData({ ...folderFormData, parent_id: e.target.value || null })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none">
                  <option value="">None (Root level)</option>
                  {folders.filter(f => f.id !== editingFolder?.id).map(f => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-3 cursor-pointer" data-testid="folder-privacy-toggle">
                <div className={`w-10 h-6 rounded-full transition-colors relative ${folderFormData.is_private ? 'bg-[#EF4444]' : 'bg-[#39FF14]/30'}`}
                  onClick={(e) => { e.preventDefault(); setFolderFormData({ ...folderFormData, is_private: !folderFormData.is_private }); }}>
                  <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${folderFormData.is_private ? 'translate-x-5' : 'translate-x-1'}`} />
                </div>
                <div className="flex items-center gap-2">
                  {folderFormData.is_private ? <Lock size={16} className="text-[#EF4444]" /> : <LockOpen size={16} className="text-[#39FF14]" />}
                  <span className="text-sm text-white">{folderFormData.is_private ? 'Private' : 'Public'}</span>
                </div>
              </label>
              <div className="flex gap-4 mt-6">
                <button data-testid="cancel-folder-btn" type="button"
                  onClick={() => { setShowFolderModal(false); setEditingFolder(null); }}
                  className="flex-1 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
                  Cancel
                </button>
                <button data-testid="submit-folder-btn" type="submit"
                  className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors">
                  {editingFolder ? 'Save' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Share Modal */}
      {showShareModal && sharingFolder && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-6 z-50">
          <div className="bg-[#141414] border border-white/10 w-full max-w-md p-8">
            <div className="flex items-center gap-3 mb-6">
              <ShareNetwork size={28} className="text-[#4ADE80]" />
              <h3 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Share Folder</h3>
            </div>
            {sharingFolder.share_token ? (
              <div>
                <p className="text-sm text-[#A3A3A3] mb-4">
                  Anyone with this link can view <strong className="text-white">{sharingFolder.name}</strong> and its matches, analyses, clips, and annotations — no login required.
                </p>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex-1 bg-[#0A0A0A] border border-white/10 text-[#007AFF] px-4 py-3 text-sm font-mono truncate select-all">
                    {window.location.origin}/api/og/folder/{sharingFolder.share_token}
                  </div>
                  <button data-testid="copy-share-link-btn" onClick={copyShareLink}
                    className={`px-4 py-3 font-bold tracking-wider uppercase transition-colors flex items-center gap-2 text-sm ${
                      copied ? 'bg-[#4ADE80] text-black' : 'bg-[#007AFF] hover:bg-[#005bb5] text-white'
                    }`}>
                    {copied ? <><Check size={16} weight="bold" /> Copied</> : <><Copy size={16} /> Copy</>}
                  </button>
                </div>
                <div className="text-[10px] text-[#10B981] tracking-[0.15em] uppercase font-bold mb-3 flex items-center gap-1.5">
                  <Check size={11} weight="bold" /> Smart link — unfurls with rich preview in WhatsApp, Slack, Twitter
                </div>
                <a data-testid="folder-preview-link" target="_blank" rel="noopener noreferrer"
                  href={`${window.location.origin}/shared/${sharingFolder.share_token}`}
                  className="block text-xs text-[#A3A3A3] hover:text-white underline underline-offset-2 mb-6">
                  Open public folder in new tab →
                </a>
                <button data-testid="revoke-share-btn"
                  onClick={handleRevokeShare}
                  className="w-full bg-transparent border border-[#EF4444]/30 text-[#EF4444] py-2 text-xs font-bold tracking-wider uppercase hover:bg-[#EF4444]/10 transition-colors">
                  Revoke Share Link
                </button>
              </div>
            ) : (
              <p className="text-sm text-[#A3A3A3]">Sharing has been revoked for this folder.</p>
            )}
            <button data-testid="close-share-modal-btn"
              onClick={() => setShowShareModal(false)}
              className="w-full mt-4 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
