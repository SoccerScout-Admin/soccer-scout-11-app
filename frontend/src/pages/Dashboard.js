import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import { Plus, VideoCamera, CaretRight, Globe, ChartLineUp } from '@phosphor-icons/react';
import CoachPulseCard from './components/CoachPulseCard';
import GameOfTheWeekBanner from './components/GameOfTheWeekBanner';
import DashboardHeader from './components/DashboardHeader';
import FolderSidebar from './components/FolderSidebar';
import MatchCard from './components/MatchCard';
import CreateMatchModal from './components/CreateMatchModal';
import FolderFormModal from './components/FolderFormModal';
import ShareFolderModal from './components/ShareFolderModal';
import BulkActionBar from './components/BulkActionBar';

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
  const [unreadMentions, setUnreadMentions] = useState(0);
  const navigate = useNavigate();
  const user = getCurrentUser();

  const fetchMatches = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/matches`, { headers: getAuthHeader() });
      setMatches(response.data);
    } catch (err) { console.error('Failed to fetch matches:', err); }
  }, []);

  const fetchFolders = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/folders`, { headers: getAuthHeader() });
      setFolders(response.data);
      const expanded = {};
      response.data.forEach(f => { expanded[f.id] = true; });
      setExpandedFolders(prev => ({ ...expanded, ...prev }));
    } catch (err) { console.error('Failed to fetch folders:', err); }
  }, []);

  useEffect(() => { fetchMatches(); fetchFolders(); }, [fetchMatches, fetchFolders]);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/coach-network/mentions`, { headers: getAuthHeader() })
      .then((res) => { if (!cancelled) setUnreadMentions((res.data || []).filter((m) => !m.read_at).length); })
      .catch(() => { /* silent */ });
    return () => { cancelled = true; };
  }, []);

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
    if (folder.share_token) {
      setSharingFolder(folder);
      setShowShareModal(true);
      return;
    }
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

  const copyShareLink = () => {
    const url = `${window.location.origin}/api/og/folder/${sharingFolder.share_token}`;
    try {
      navigator.clipboard.writeText(url).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }).catch(() => { fallbackCopy(url); });
    } catch {
      fallbackCopy(url);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    navigate('/auth');
  };

  const toggleFolderExpand = (folderId) => {
    setExpandedFolders(prev => ({ ...prev, [folderId]: !prev[folderId] }));
  };

  const openNewFolder = () => {
    setEditingFolder(null);
    setFolderFormData({
      name: '',
      parent_id: (selectedFolderId && selectedFolderId !== '__none__') ? selectedFolderId : null,
      is_private: false,
    });
    setShowFolderModal(true);
  };

  const openEditFolder = (folder) => {
    setEditingFolder(folder);
    setFolderFormData({ name: folder.name, parent_id: folder.parent_id, is_private: folder.is_private });
    setShowFolderModal(true);
  };

  const flatFolderList = useMemo(() => {
    const result = [];
    const addChildren = (parentId, depth) => {
      const children = folders.filter(f => (f.parent_id || null) === parentId).sort((a, b) => a.name.localeCompare(b.name));
      for (const folder of children) {
        const hasChildren = folders.some(f => f.parent_id === folder.id);
        const isExpanded = expandedFolders[folder.id] !== false;
        result.push({ ...folder, depth, hasChildren, isExpanded });
        if (hasChildren && isExpanded) addChildren(folder.id, depth + 1);
      }
    };
    addChildren(null, 0);
    return result;
  }, [folders, expandedFolders]);

  const displayMatches = selectedFolderId === '__none__'
    ? matches.filter(m => !m.folder_id)
    : selectedFolderId
    ? matches.filter(m => m.folder_id === selectedFolderId)
    : matches;

  const selectedFolderName = selectedFolderId === '__none__'
    ? 'Unsorted Matches'
    : selectedFolderId
    ? (folders.find(f => f.id === selectedFolderId)?.name || 'Folder')
    : 'Match Library';

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <DashboardHeader user={user} unreadMentions={unreadMentions}
        onNavigate={navigate} onLogout={handleLogout} />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 flex flex-col lg:flex-row gap-4 lg:gap-6">
        <FolderSidebar
          matches={matches}
          flatFolderList={flatFolderList}
          selectedFolderId={selectedFolderId}
          setSelectedFolderId={setSelectedFolderId}
          folderMenuId={folderMenuId}
          setFolderMenuId={setFolderMenuId}
          onToggleExpand={toggleFolderExpand}
          onOpenNewFolder={openNewFolder}
          onEditFolder={openEditFolder}
          onShareFolder={handleToggleShare}
          onTrendsFolder={(id) => navigate(`/folder/${id}/trends`)}
          onDeleteFolder={handleDeleteFolder}
        />

        <main className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h2 className="text-4xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>{selectedFolderName}</h2>
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

          {!selectionMode && (
            <>
              <GameOfTheWeekBanner />
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

          {selectionMode && (
            <BulkActionBar selectedCount={selectedMatchIds.length} bulkBusy={bulkBusy} folders={folders}
              onMove={bulkMove} onSetCompetition={bulkSetCompetition} onDelete={bulkDelete} />
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
                <MatchCard key={match.id} match={match} folders={folders}
                  selectionMode={selectionMode}
                  isSelected={selectedMatchIds.includes(match.id)}
                  onNavigate={navigate}
                  onToggleSelect={toggleMatchSelection}
                  onMoveMatch={handleMoveMatch} />
              ))}
            </div>
          )}
        </main>
      </div>

      <CreateMatchModal open={showCreateModal} onClose={() => setShowCreateModal(false)}
        onSubmit={handleCreateMatch} formData={formData} setFormData={setFormData} loading={loading} />

      <FolderFormModal open={showFolderModal}
        onClose={() => { setShowFolderModal(false); setEditingFolder(null); }}
        onSubmit={handleCreateFolder}
        folderFormData={folderFormData} setFolderFormData={setFolderFormData}
        editingFolder={editingFolder} folders={folders} />

      <ShareFolderModal open={showShareModal} sharingFolder={sharingFolder}
        onClose={() => setShowShareModal(false)}
        onCopy={copyShareLink} onRevoke={handleRevokeShare} copied={copied} />
    </div>
  );
};

export default Dashboard;
