import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser, clearSession } from '../App';
import { Plus, VideoCamera, CaretRight, Globe, ChartLineUp, DeviceMobile } from '@phosphor-icons/react';
import { useMatches } from '../hooks/useMatches';
import { useFolders } from '../hooks/useFolders';
import CoachPulseCard from './components/CoachPulseCard';
import GameOfTheWeekBanner from './components/GameOfTheWeekBanner';
import DashboardHeader from './components/DashboardHeader';
import FolderSidebar from './components/FolderSidebar';
import MatchCard from './components/MatchCard';
import CreateMatchModal from './components/CreateMatchModal';
import FolderFormModal from './components/FolderFormModal';
import ShareFolderModal from './components/ShareFolderModal';
import BulkActionBar from './components/BulkActionBar';
import QuickActionsRow from './components/QuickActionsRow';
import MyReelStatsCard from './components/MyReelStatsCard';
import InstallGuideModal from '../components/InstallGuideModal';
import BuildInfoChip from '../components/BuildInfoChip';

/**
 * Copy-to-clipboard with execCommand fallback for older browsers / iOS Safari.
 * Returns true on success.
 */
const copyToClipboard = (text) => {
  try {
    return navigator.clipboard.writeText(text).then(() => true).catch(() => false);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    document.body.removeChild(ta);
    return Promise.resolve(ok);
  }
};

const Dashboard = () => {
  const navigate = useNavigate();
  const user = getCurrentUser();

  const [selectedFolderId, setSelectedFolderId] = useState(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [showInstallGuide, setShowInstallGuide] = useState(false);
  const [sharingFolder, setSharingFolder] = useState(null);
  const [copied, setCopied] = useState(false);
  const [editingFolder, setEditingFolder] = useState(null);
  const [folderMenuId, setFolderMenuId] = useState(null);
  const [formData, setFormData] = useState({ team_home: '', team_away: '', date: '', competition: '' });
  const [folderFormData, setFolderFormData] = useState({ name: '', parent_id: null, is_private: false });
  const [loading, setLoading] = useState(false);
  const [unreadMentions, setUnreadMentions] = useState(0);
  const [unreadMessages, setUnreadMessages] = useState(0);

  // Data layer — see /app/frontend/src/hooks/{useMatches,useFolders}.js
  const m = useMatches(selectedFolderId);
  const f = useFolders();

  // Unread counts (mentions + messages) — small enough to leave inline
  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/coach-network/mentions`, { headers: getAuthHeader() })
      .then((res) => { if (!cancelled) setUnreadMentions((res.data || []).filter((x) => !x.read_at).length); })
      .catch(() => { /* silent */ });
    axios.get(`${API}/messages/unread-count`, { headers: getAuthHeader() })
      .then((res) => { if (!cancelled) setUnreadMessages(res.data?.unread || 0); })
      .catch(() => { /* silent */ });
    return () => { cancelled = true; };
  }, []);

  // ===== Modal coordination handlers (page-local UI concerns) =====

  const handleCreateMatch = async (e, opts = {}) => {
    e.preventDefault();
    setLoading(true);
    try {
      const created = await m.createMatch(formData);
      if (!opts.keepOpen) {
        setShowCreateModal(false);
        setFormData({ team_home: '', team_away: '', date: '', competition: '' });
      }
      return created;  // CreateMatchModal needs match.id to advance to the Roster step
    } catch (err) {
      console.error('Failed to create match:', err);
      return null;
    } finally { setLoading(false); }
  };

  const handleCreateFolder = async (e) => {
    e.preventDefault();
    try {
      await f.createOrUpdateFolder({ editingFolder, folderFormData, selectedFolderId });
      setShowFolderModal(false);
      setEditingFolder(null);
      setFolderFormData({ name: '', parent_id: null, is_private: false });
    } catch (err) { console.error('Failed to save folder:', err); }
  };

  const handleDeleteFolder = async (folderId) => {
    await f.deleteFolder(folderId, (cleared) => {
      if (selectedFolderId === cleared) setSelectedFolderId(null);
      m.fetchMatches();
    });
  };

  const handleToggleShare = async (folder) => {
    try {
      if (folder.share_token) {
        setSharingFolder(folder);
        setShowShareModal(true);
        return;
      }
      const updated = await f.toggleShare(folder);
      setSharingFolder(updated);
      setShowShareModal(true);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to share folder');
    }
  };

  const handleRevokeShare = async () => {
    if (!sharingFolder) return;
    try {
      await f.revokeShare(sharingFolder);
      setSharingFolder({ ...sharingFolder, share_token: null });
      setShowShareModal(false);
    } catch {
      alert('Failed to revoke share link');
    }
  };

  const copyShareLink = async () => {
    if (!sharingFolder?.share_token) return;
    const url = `${window.location.origin}/api/og/folder/${sharingFolder.share_token}`;
    const ok = await copyToClipboard(url);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      alert('Copy failed — please select and copy the link manually.');
    }
  };

  const handleLogout = async () => {
    await clearSession();
    navigate('/auth');
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

  const selectedFolderName = (() => {
    if (selectedFolderId === '__none__') return 'Unsorted Matches';
    if (selectedFolderId) return f.folders.find((x) => x.id === selectedFolderId)?.name || 'Folder';
    return 'Match Library';
  })();

  // First-run experience — coaches with zero matches across the whole library
  // shouldn't see promo cards (Reel Stats, Game of the Week, Coach Pulse,
  // Coach Network CTA) that have nothing to render against. They surface
  // automatically once the first match is created. See user feedback on
  // production deploy 2026-05-13.
  const hasAnyMatches = m.matches.length > 0;

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <DashboardHeader user={user} unreadMentions={unreadMentions} unreadMessages={unreadMessages}
        onNavigate={navigate} onLogout={handleLogout} />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 flex flex-col lg:flex-row gap-4 lg:gap-6">
        <FolderSidebar
          matches={m.matches}
          flatFolderList={f.flatFolderList}
          selectedFolderId={selectedFolderId}
          setSelectedFolderId={setSelectedFolderId}
          folderMenuId={folderMenuId}
          setFolderMenuId={setFolderMenuId}
          onToggleExpand={f.toggleFolderExpand}
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
              <p className="text-[#A3A3A3] tracking-wide">{m.displayMatches.length} match{m.displayMatches.length !== 1 ? 'es' : ''}</p>
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
              onClick={() => m.selectionMode ? m.exitSelectionMode() : m.setSelectionMode(true)}
              className={`px-4 py-3 font-bold tracking-wider uppercase text-xs transition-colors border ${
                m.selectionMode ? 'border-[#FBBF24] text-[#FBBF24] bg-[#FBBF24]/10' : 'border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F]'
              }`}>
              {m.selectionMode ? 'Done' : 'Select'}
            </button>
          </div>

          {!m.selectionMode && (
            <>
              <QuickActionsRow onCreate={() => setShowCreateModal(true)} />
              {hasAnyMatches && (
                <>
                  <MyReelStatsCard />
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
            </>
          )}

          {m.selectionMode && (
            <BulkActionBar selectedCount={m.selectedMatchIds.length} bulkBusy={m.bulkBusy} folders={f.folders}
              onMove={m.bulkMove} onSetCompetition={m.bulkSetCompetition} onDelete={m.bulkDelete} />
          )}

          {m.displayMatches.length === 0 ? (
            <div className="text-center py-20" data-testid="match-library-empty-state">
              <VideoCamera size={80} className="text-[#A3A3A3] mx-auto mb-4" />
              {!hasAnyMatches ? (
                <>
                  <p className="text-2xl text-white font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                    Welcome to SoccerScout11
                  </p>
                  <p className="text-sm text-[#A3A3A3] max-w-md mx-auto mb-6">
                    Upload your first match film and let the AI break down the game — clips, timeline markers, and a shareable recap all generated automatically.
                  </p>
                  <button
                    data-testid="empty-state-create-match-btn"
                    onClick={() => setShowCreateModal(true)}
                    className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors inline-flex items-center gap-2">
                    <Plus size={16} weight="bold" /> Create Your First Match
                  </button>
                </>
              ) : (
                <>
                  <p className="text-xl text-[#A3A3A3] mb-2">No matches here</p>
                  <p className="text-sm text-[#A3A3A3]">Create a match or move one into this folder</p>
                </>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {m.displayMatches.map((match) => (
                <MatchCard key={match.id} match={match} folders={f.folders}
                  selectionMode={m.selectionMode}
                  isSelected={m.selectedMatchIds.includes(match.id)}
                  onNavigate={navigate}
                  onToggleSelect={m.toggleMatchSelection}
                  onMoveMatch={m.moveMatch}
                  onDeleteMatch={m.deleteMatch} />
              ))}
            </div>
          )}
        </main>
      </div>

      <CreateMatchModal open={showCreateModal}
        onClose={() => {
          setShowCreateModal(false);
          setFormData({ team_home: '', team_away: '', date: '', competition: '' });
        }}
        onSubmit={handleCreateMatch} formData={formData} setFormData={setFormData} loading={loading} />

      <FolderFormModal open={showFolderModal}
        onClose={() => { setShowFolderModal(false); setEditingFolder(null); }}
        onSubmit={handleCreateFolder}
        folderFormData={folderFormData} setFolderFormData={setFolderFormData}
        editingFolder={editingFolder} folders={f.folders} />

      <ShareFolderModal open={showShareModal} sharingFolder={sharingFolder}
        onClose={() => setShowShareModal(false)}
        onCopy={copyShareLink} onRevoke={handleRevokeShare} copied={copied} />

      {showInstallGuide && <InstallGuideModal onClose={() => setShowInstallGuide(false)} />}

      {/* Discreet footer link — drives org-wide adoption (assistant coaches, players) */}
      <footer className="border-t border-white/5 px-4 sm:px-6 py-3 mt-8">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <BuildInfoChip />
          <button
            data-testid="install-on-another-device-btn"
            onClick={() => setShowInstallGuide(true)}
            className="flex items-center gap-1.5 text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3] hover:text-[#007AFF] transition-colors">
            <DeviceMobile size={12} weight="bold" />
            Install on Another Device
          </button>
        </div>
      </footer>
    </div>
  );
};

export default Dashboard;
