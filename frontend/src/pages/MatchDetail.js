import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, UploadSimple, VideoCamera, Spinner, Users, Plus, Trash, FileText } from '@phosphor-icons/react';

const MatchDetail = () => {
  const { matchId } = useParams();
  const navigate = useNavigate();
  const [match, setMatch] = useState(null);
  const [players, setPlayers] = useState([]);
  const [showRosterPanel, setShowRosterPanel] = useState(false);
  const [showAddPlayer, setShowAddPlayer] = useState(false);
  const [showCsvImport, setShowCsvImport] = useState(false);
  const [playerForm, setPlayerForm] = useState({ name: '', number: '', position: '', team: '' });
  const [csvData, setCsvData] = useState('');
  const [csvTeam, setCsvTeam] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('');

  useEffect(() => {
    fetchMatch();
    fetchPlayers();
  }, [matchId]);

  const fetchMatch = async () => {
    try {
      const response = await axios.get(`${API}/matches/${matchId}`, { headers: getAuthHeader() });
      setMatch(response.data);
    } catch (err) {
      console.error('Failed to fetch match:', err);
    }
  };

  const fetchPlayers = async () => {
    try {
      const response = await axios.get(`${API}/players/match/${matchId}`, { headers: getAuthHeader() });
      setPlayers(response.data);
    } catch (err) {
      console.error('Failed to fetch players:', err);
    }
  };

  const handleAddPlayer = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/players`, {
        match_id: matchId,
        name: playerForm.name,
        number: playerForm.number ? parseInt(playerForm.number) : null,
        position: playerForm.position,
        team: playerForm.team || match?.team_home || ''
      }, { headers: getAuthHeader() });
      setPlayerForm({ name: '', number: '', position: '', team: '' });
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
        match_id: matchId,
        csv_data: csvData,
        team: csvTeam
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
    reader.onload = (ev) => {
      setCsvData(ev.target.result);
    };
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

  const handleVideoUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.type.startsWith('video/')) {
      alert('Please select a valid video file');
      return;
    }
    const fileSizeGB = file.size / (1024 * 1024 * 1024);
    if (file.size > 1024 * 1024 * 1024) {
      alert(`Uploading large file (${fileSizeGB.toFixed(2)}GB). This may take several minutes.`);
      await handleChunkedUpload(file);
    } else {
      await handleStandardUpload(file);
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

  // Group players by team
  const homeTeamPlayers = players.filter(p => p.team === match?.team_home);
  const awayTeamPlayers = players.filter(p => p.team === match?.team_away);
  const otherPlayers = players.filter(p => p.team !== match?.team_home && p.team !== match?.team_away);

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
        {/* Match Info + Upload */}
        <div className="bg-[#141414] border border-white/10 p-8 mb-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <p className="text-xs text-[#A3A3A3] uppercase tracking-wider mb-2">{match.competition || 'Friendly'}</p>
              <h2 className="text-5xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                {match.team_home} vs {match.team_away}
              </h2>
              <p className="text-[#A3A3A3]">{new Date(match.date + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</p>
            </div>
          </div>

          {!match.video_id ? (
            <div className="border-2 border-dashed border-white/10 p-12 text-center">
              <VideoCamera size={64} className="text-[#A3A3A3] mx-auto mb-4" />
              <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Upload Match Video</h3>
              <p className="text-[#A3A3A3] mb-6">Upload footage to enable AI analysis and annotations</p>
              {uploading ? (
                <div className="max-w-md mx-auto">
                  <div className="bg-[#0A0A0A] h-3 mb-3 rounded-full overflow-hidden">
                    <div className="bg-[#007AFF] h-3 rounded-full" style={{ width: `${uploadProgress}%`, transition: 'width 0.3s ease' }} />
                  </div>
                  <p className="text-sm text-white font-medium mb-1">{uploadProgress}%</p>
                  {uploadStatus && <p className="text-xs text-[#A3A3A3]" data-testid="upload-status-text">{uploadStatus}</p>}
                </div>
              ) : (
                <label data-testid="upload-video-btn"
                  className="inline-flex items-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors cursor-pointer">
                  <UploadSimple size={24} weight="bold" />
                  Select Video File
                  <input type="file" accept="video/*" onChange={handleVideoUpload} className="hidden" />
                </label>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-[#39FF14]">
                <VideoCamera size={24} />
                <span className="font-bold tracking-wider uppercase">Video Uploaded</span>
              </div>
              <button data-testid="view-analysis-btn" onClick={() => navigate(`/video/${match.video_id}`)}
                className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase transition-colors">
                View Analysis
              </button>
            </div>
          )}
        </div>

        {/* Player Roster Section */}
        <div className="bg-[#141414] border border-white/10 p-8" data-testid="roster-section">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <Users size={24} className="text-[#007AFF]" />
              <h3 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Player Roster</h3>
              <span className="text-xs text-[#A3A3A3] bg-white/5 px-2 py-1">{players.length} players</span>
            </div>
            <div className="flex gap-2">
              <button data-testid="import-csv-btn"
                onClick={() => setShowCsvImport(!showCsvImport)}
                className="flex items-center gap-2 px-4 py-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold tracking-wider uppercase">
                <FileText size={16} /> CSV Import
              </button>
              <button data-testid="add-player-btn"
                onClick={() => setShowAddPlayer(!showAddPlayer)}
                className="flex items-center gap-2 px-4 py-2 bg-[#007AFF] hover:bg-[#005bb5] text-white transition-colors text-xs font-bold tracking-wider uppercase">
                <Plus size={16} weight="bold" /> Add Player
              </button>
            </div>
          </div>

          {/* CSV Import Form */}
          {showCsvImport && (
            <div className="bg-[#0A0A0A] border border-white/10 p-6 mb-6">
              <h4 className="text-sm font-bold uppercase tracking-wider text-white mb-3">Import from CSV</h4>
              <p className="text-xs text-[#A3A3A3] mb-4">Upload a CSV file or paste CSV data with columns: <code className="text-[#007AFF]">name, number, position</code></p>
              <form onSubmit={handleCsvImport} className="space-y-3">
                <div>
                  <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Team Name</label>
                  <select data-testid="csv-team-select" value={csvTeam}
                    onChange={(e) => setCsvTeam(e.target.value)}
                    className="w-full bg-[#141414] border border-white/10 text-white px-4 py-2 focus:border-[#007AFF] focus:outline-none text-sm">
                    <option value="">Select team...</option>
                    <option value={match.team_home}>{match.team_home} (Home)</option>
                    <option value={match.team_away}>{match.team_away} (Away)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">CSV File</label>
                  <input data-testid="csv-file-input" type="file" accept=".csv,.txt"
                    onChange={handleFileUpload}
                    className="w-full text-[#A3A3A3] text-sm file:bg-[#007AFF] file:text-white file:border-0 file:px-4 file:py-2 file:mr-4 file:cursor-pointer" />
                </div>
                <div>
                  <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Or Paste CSV Data</label>
                  <textarea data-testid="csv-data-input" value={csvData}
                    onChange={(e) => setCsvData(e.target.value)}
                    className="w-full bg-[#141414] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none text-sm font-mono resize-none"
                    rows="5" placeholder="name,number,position&#10;John Doe,10,Forward&#10;Jane Smith,1,Goalkeeper" />
                </div>
                <div className="flex gap-3">
                  <button data-testid="cancel-csv-btn" type="button" onClick={() => setShowCsvImport(false)}
                    className="px-4 py-2 border border-white/10 text-white text-xs font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
                    Cancel
                  </button>
                  <button data-testid="submit-csv-btn" type="submit" disabled={!csvData.trim()}
                    className="px-6 py-2 bg-[#007AFF] hover:bg-[#005bb5] text-white text-xs font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
                    Import
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Add Player Form */}
          {showAddPlayer && (
            <div className="bg-[#0A0A0A] border border-white/10 p-6 mb-6">
              <h4 className="text-sm font-bold uppercase tracking-wider text-white mb-3">Add Player</h4>
              <form onSubmit={handleAddPlayer} className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Name *</label>
                  <input data-testid="player-name-input" type="text" value={playerForm.name}
                    onChange={(e) => setPlayerForm({ ...playerForm, name: e.target.value })}
                    className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none"
                    required />
                </div>
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Number</label>
                  <input data-testid="player-number-input" type="number" value={playerForm.number}
                    onChange={(e) => setPlayerForm({ ...playerForm, number: e.target.value })}
                    className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none" />
                </div>
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Position</label>
                  <select data-testid="player-position-select" value={playerForm.position}
                    onChange={(e) => setPlayerForm({ ...playerForm, position: e.target.value })}
                    className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none">
                    <option value="">Select...</option>
                    <option value="Goalkeeper">Goalkeeper</option>
                    <option value="Defender">Defender</option>
                    <option value="Midfielder">Midfielder</option>
                    <option value="Forward">Forward</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Team</label>
                  <select data-testid="player-team-select" value={playerForm.team}
                    onChange={(e) => setPlayerForm({ ...playerForm, team: e.target.value })}
                    className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none">
                    <option value="">{match.team_home} (default)</option>
                    <option value={match.team_home}>{match.team_home}</option>
                    <option value={match.team_away}>{match.team_away}</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <button data-testid="cancel-add-player-btn" type="button" onClick={() => setShowAddPlayer(false)}
                    className="px-3 py-2 border border-white/10 text-white text-xs hover:bg-[#1F1F1F] transition-colors">
                    Cancel
                  </button>
                  <button data-testid="submit-add-player-btn" type="submit"
                    className="px-4 py-2 bg-[#007AFF] hover:bg-[#005bb5] text-white text-xs font-bold tracking-wider uppercase transition-colors">
                    Add
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Player List */}
          {players.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-white/10">
              <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
              <p className="text-[#A3A3A3] mb-1">No players added yet</p>
              <p className="text-xs text-[#666]">Add players manually or import from CSV</p>
            </div>
          ) : (
            <div className="space-y-6">
              {[
                { label: match.team_home, players: homeTeamPlayers, color: '#007AFF' },
                { label: match.team_away, players: awayTeamPlayers, color: '#EF4444' },
                ...(otherPlayers.length > 0 ? [{ label: 'Other', players: otherPlayers, color: '#A3A3A3' }] : [])
              ].filter(g => g.players.length > 0).map(group => (
                <div key={group.label}>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-3 h-3" style={{ backgroundColor: group.color }} />
                    <h4 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">
                      {group.label} ({group.players.length})
                    </h4>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                    {group.players.sort((a, b) => (a.number || 99) - (b.number || 99)).map(player => (
                      <div key={player.id} data-testid={`player-card-${player.id}`}
                        className="flex items-center gap-3 bg-[#0A0A0A] border border-white/5 px-4 py-3 group hover:border-white/10 transition-colors">
                        <div className="w-8 h-8 flex items-center justify-center text-sm font-bold"
                          style={{ backgroundColor: group.color + '20', color: group.color }}>
                          {player.number || '—'}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-white font-medium truncate">{player.name}</p>
                          <p className="text-[10px] text-[#666] uppercase tracking-wider">{player.position || 'Unknown'}</p>
                        </div>
                        <button data-testid={`delete-player-${player.id}-btn`} onClick={() => handleDeletePlayer(player.id)}
                          className="opacity-0 group-hover:opacity-100 transition-opacity text-[#666] hover:text-[#EF4444]">
                          <Trash size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default MatchDetail;
