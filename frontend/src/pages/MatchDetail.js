import { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, Spinner, Trash } from '@phosphor-icons/react';
import ManualResultForm from './components/ManualResultForm';
import UploadPanel from './components/UploadPanel';
import DeletedVideosDrawer from './components/DeletedVideosDrawer';
import ConfirmReuploadModal from './components/ConfirmReuploadModal';
import RosterSection from './components/RosterSection';
import ProcessingProgressBar from './components/ProcessingProgressBar';

const MatchDetail = () => {
  const { matchId } = useParams();
  const navigate = useNavigate();
  const [match, setMatch] = useState(null);
  const [players, setPlayers] = useState([]);
  const [teams, setTeams] = useState([]);
  const [showAddPlayer, setShowAddPlayer] = useState(false);
  const [showCsvImport, setShowCsvImport] = useState(false);
  const [playerForm, setPlayerForm] = useState({ name: '', number: '', position: '', team: '', team_id: '' });
  const [csvData, setCsvData] = useState('');
  const [csvTeam, setCsvTeam] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('');
  const [videoMeta, setVideoMeta] = useState(null);
  const [confirmReupload, setConfirmReupload] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletedVideos, setDeletedVideos] = useState([]);
  const [showDeletedDrawer, setShowDeletedDrawer] = useState(false);

  const fetchMatch = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/matches/${matchId}`, { headers: getAuthHeader() });
      setMatch(response.data);
    } catch (err) {
      console.error('Failed to fetch match:', err);
    }
  }, [matchId]);

  const fetchPlayers = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/players/match/${matchId}`, { headers: getAuthHeader() });
      setPlayers(response.data);
    } catch (err) {
      console.error('Failed to fetch players:', err);
    }
  }, [matchId]);

  const fetchTeams = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/teams`, { headers: getAuthHeader() });
      setTeams(response.data);
    } catch (err) { console.error('Failed to fetch teams:', err); }
  }, []);

  useEffect(() => {
    fetchMatch();
    fetchPlayers();
    fetchTeams();
  }, [fetchMatch, fetchPlayers, fetchTeams]);

  useEffect(() => {
    if (!match?.video_id) { setVideoMeta(null); return; }
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await axios.get(`${API}/videos/${match.video_id}/processing-status`, { headers: getAuthHeader() });
        if (!cancelled) setVideoMeta(res.data);
      } catch { /* video may not exist yet */ }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [match?.video_id]);

  const fetchDeletedVideos = async () => {
    try {
      const res = await axios.get(`${API}/matches/${matchId}/deleted-videos`, { headers: getAuthHeader() });
      setDeletedVideos(res.data);
    } catch (err) { /* ignore */ }
  };

  const handleRestoreVideo = async (videoId) => {
    if (!window.confirm('Restore this video? Note: any clips, AI markers, and analyses created before deletion are gone — only the video file is recoverable.')) return;
    try {
      await axios.post(`${API}/videos/${videoId}/restore`, {}, { headers: getAuthHeader() });
      setShowDeletedDrawer(false);
      setDeletedVideos([]);
      await fetchMatch();
    } catch (err) {
      alert('Restore failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleDeleteVideo = async () => {
    if (!match?.video_id) return;
    setDeleting(true);
    try {
      await axios.delete(`${API}/videos/${match.video_id}`, { headers: getAuthHeader() });
      setConfirmReupload(false);
      setVideoMeta(null);
      await fetchMatch();
    } catch (err) {
      alert('Failed to delete video: ' + (err.response?.data?.detail || err.message));
    } finally {
      setDeleting(false);
    }
  };

  const handleAddPlayer = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        match_id: matchId,
        name: playerForm.name,
        number: playerForm.number !== '' ? parseInt(playerForm.number) : null,
        position: playerForm.position,
        team: playerForm.team || match?.team_home || ''
      };
      if (playerForm.team_id) payload.team_id = playerForm.team_id;
      await axios.post(`${API}/players`, payload, { headers: getAuthHeader() });
      setPlayerForm({ name: '', number: '', position: '', team: '', team_id: '' });
      setShowAddPlayer(false);
      fetchPlayers();
    } catch (err) {
      console.error('Failed to add player:', err);
    }
  };

  const handleCsvImport = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post(`${API}/players/import-csv`, {
        match_id: matchId, csv_data: csvData, team: csvTeam
      }, { headers: getAuthHeader() });
      setCsvData('');
      setCsvTeam('');
      setShowCsvImport(false);
      fetchPlayers();
      alert(`Imported ${res.data.imported} players successfully.`);
    } catch (err) {
      console.error('CSV import failed:', err);
      alert('CSV import failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setCsvData(ev.target.result);
    reader.readAsText(file);
  };

  const handleDeletePlayer = async (playerId) => {
    try {
      await axios.delete(`${API}/players/${playerId}`, { headers: getAuthHeader() });
      setPlayers(players.filter(p => p.id !== playerId));
    } catch (err) {
      console.error('Failed to delete player:', err);
    }
  };

  const handleStandardUpload = async (file) => {
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await axios.post(`${API}/videos/upload?match_id=${matchId}`, formData, {
        headers: getAuthHeader(),
        onUploadProgress: (progressEvent) => {
          setUploadProgress(Math.round((progressEvent.loaded * 100) / progressEvent.total));
        },
        timeout: 600000
      });
      navigate(`/video/${response.data.video_id}`);
    } catch (err) {
      console.error('Upload failed:', err);
      alert(err.response?.data?.detail || 'Video upload failed.');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const uploadChunkWithRetry = async (url, formData, maxRetries = 3) => {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        return await axios.post(url, formData, { headers: getAuthHeader(), timeout: 300000 });
      } catch (err) {
        const isRetryable = !err.response || err.response.status >= 500 || err.code === 'ECONNABORTED';
        if (attempt === maxRetries || !isRetryable) throw err;
        await new Promise(r => setTimeout(r, Math.min(2000 * Math.pow(2, attempt - 1), 30000)));
      }
    }
  };

  const handleChunkedUpload = async (file) => {
    setUploading(true);
    setUploadStatus('Initializing upload...');
    try {
      const initResponse = await axios.post(`${API}/videos/upload/init`, {
        match_id: matchId, filename: file.name, file_size: file.size, content_type: file.type || 'video/mp4'
      }, { headers: getAuthHeader(), timeout: 30000 });

      const { upload_id, video_id, chunk_size, resume, uploaded_chunks } = initResponse.data;
      const totalChunks = Math.ceil(file.size / chunk_size);
      const uploadedSet = new Set(uploaded_chunks || []);
      const chunksToUpload = [];
      for (let i = 0; i < totalChunks; i++) {
        if (!uploadedSet.has(i)) chunksToUpload.push(i);
      }
      let uploadedCount = totalChunks - chunksToUpload.length;

      if (resume && uploadedCount > 0) {
        const pct = Math.round((uploadedCount / totalChunks) * 100);
        setUploadProgress(pct);
        setUploadStatus(`Resuming: ${uploadedCount}/${totalChunks} chunks done — ${chunksToUpload.length} remaining`);
      }

      for (const i of chunksToUpload) {
        const start = i * chunk_size;
        const chunk = file.slice(start, Math.min(start + chunk_size, file.size));
        const chunkFormData = new FormData();
        chunkFormData.append('file', chunk);
        const resp = await uploadChunkWithRetry(
          `${API}/videos/upload/chunk?upload_id=${upload_id}&chunk_index=${i}&total_chunks=${totalChunks}`, chunkFormData);
        uploadedCount++;
        setUploadProgress(Math.round((uploadedCount / totalChunks) * 100));
        setUploadStatus(`Uploading: ${uploadedCount}/${totalChunks} chunks`);
        if (resp.data.status === 'completed') break;
      }
      navigate(`/video/${video_id}`);
    } catch (err) {
      console.error('Chunked upload failed:', err);
      alert('Upload interrupted. Try again — it will resume.\n' + (err.response?.data?.detail || err.message));
    } finally {
      setUploading(false);
      setUploadProgress(0);
      setUploadStatus('');
    }
  };

  const handleVideoUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.type.startsWith('video/')) {
      alert('Please select a valid video file');
      return;
    }
    const fileSizeGB = file.size / (1024 * 1024 * 1024);
    if (file.size > 1024 * 1024 * 1024) {
      const mins = Math.max(5, Math.round(fileSizeGB * 4));
      const ok = window.confirm(
        `Large file detected (${fileSizeGB.toFixed(2)} GB).\n\n` +
        `We'll upload in resumable chunks — keep this tab open. ` +
        `On a typical home network this takes ~${mins} minutes. ` +
        `If your connection drops, the upload will resume from where it left off.\n\nContinue?`
      );
      if (!ok) return;
      handleChunkedUpload(file);
    } else {
      handleStandardUpload(file);
    }
  };

  const handleReprocessVideo = async () => {
    if (!match?.video_id) return;
    try {
      await axios.post(`${API}/videos/${match.video_id}/reprocess`, {}, { headers: getAuthHeader() });
      setVideoMeta((prev) => ({ ...(prev || {}), processing_status: 'queued', processing_progress: 0 }));
    } catch (err) {
      alert('Failed to retry processing: ' + (err.response?.data?.detail || err.message));
    }
  };

  const playerGroups = useMemo(() => {
    const homeTeamPlayers = players.filter(p => p.team === match?.team_home);
    const awayTeamPlayers = players.filter(p => p.team === match?.team_away);
    const otherPlayers = players.filter(p => p.team !== match?.team_home && p.team !== match?.team_away);
    return [
      { label: match?.team_home, players: homeTeamPlayers, color: '#007AFF' },
      { label: match?.team_away, players: awayTeamPlayers, color: '#EF4444' },
      ...(otherPlayers.length > 0 ? [{ label: 'Other', players: otherPlayers, color: '#A3A3A3' }] : []),
    ];
  }, [players, match?.team_home, match?.team_away]);

  if (!match) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <Spinner size={48} className="text-[#007AFF] animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center gap-4">
          <button data-testid="back-to-dashboard-btn" onClick={() => navigate('/')}
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <ArrowLeft size={24} className="text-white" />
          </button>
          <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Match Details</h1>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {!match.video_id && (
          <ManualResultForm match={match} players={players} onSaved={() => fetchMatch()} />
        )}

        <div className="bg-[#141414] border border-white/10 p-8 mb-6">
          <div className="flex items-start justify-between mb-6 gap-4">
            <div className="min-w-0">
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider mb-2">{match.competition || 'Friendly'}</p>
              <h2 className="text-5xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                {match.team_home} vs {match.team_away}
              </h2>
              <p className="text-[#A3A3A3]">{new Date(match.date + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</p>
            </div>
            <button
              data-testid="delete-match-detail-btn"
              onClick={async () => {
                const confirmMsg = `Delete match "${match.team_home} vs ${match.team_away}"? `
                  + (match.video_id
                    ? 'The video enters the 24h restore window. Clips and AI analyses are removed permanently.'
                    : 'This cannot be undone.');
                if (!window.confirm(confirmMsg)) return;
                try {
                  await axios.delete(`${API}/matches/${matchId}`, { headers: getAuthHeader() });
                  navigate('/');
                } catch (err) {
                  alert('Failed to delete match: ' + (err.response?.data?.detail || err.message));
                }
              }}
              className="flex-shrink-0 flex items-center gap-2 border border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10 hover:border-[#EF4444] px-4 py-2 text-xs font-bold tracking-wider uppercase transition-colors"
              aria-label="Delete this match">
              <Trash size={14} weight="bold" /> Delete Match
            </button>
          </div>

          <UploadPanel match={match} matchId={matchId} videoMeta={videoMeta}
            uploading={uploading} uploadProgress={uploadProgress} uploadStatus={uploadStatus}
            onVideoUpload={handleVideoUpload}
            onShowDeleted={() => { fetchDeletedVideos(); setShowDeletedDrawer(true); }}
            onConfirmReupload={() => setConfirmReupload(true)}
            navigate={navigate} />
        </div>

        <ProcessingProgressBar videoMeta={videoMeta} onRetry={handleReprocessVideo} />

        {match.video_id && <HighlightReelsPanel matchId={matchId} />}

        <DeletedVideosDrawer open={showDeletedDrawer} deletedVideos={deletedVideos}
          onClose={() => setShowDeletedDrawer(false)} onRestore={handleRestoreVideo} />

        <ConfirmReuploadModal open={confirmReupload} deleting={deleting}
          onConfirm={handleDeleteVideo} onCancel={() => setConfirmReupload(false)} />

        <RosterSection
          match={match} players={players} teams={teams} playerGroups={playerGroups}
          showAddPlayer={showAddPlayer} setShowAddPlayer={setShowAddPlayer}
          showCsvImport={showCsvImport} setShowCsvImport={setShowCsvImport}
          playerForm={playerForm} setPlayerForm={setPlayerForm}
          csvData={csvData} setCsvData={setCsvData}
          csvTeam={csvTeam} setCsvTeam={setCsvTeam}
          onAddPlayer={handleAddPlayer} onCsvImport={handleCsvImport}
          onFileChange={handleFileUpload} onDeletePlayer={handleDeletePlayer} />
      </main>
    </div>
  );
};

export default MatchDetail;
