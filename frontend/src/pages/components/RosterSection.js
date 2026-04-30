import { Users, Plus, Trash, FileText } from '@phosphor-icons/react';

const CsvImportForm = ({ match, csvData, setCsvData, csvTeam, setCsvTeam, onFileChange, onSubmit, onCancel }) => (
  <div className="bg-[#0A0A0A] border border-white/10 p-6 mb-6">
    <h4 className="text-sm font-bold uppercase tracking-wider text-white mb-3">Import from CSV</h4>
    <p className="text-xs text-[#A3A3A3] mb-4">Upload a CSV file or paste CSV data with columns: <code className="text-[#007AFF]">name, number, position</code></p>
    <form onSubmit={onSubmit} className="space-y-3">
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
        <input data-testid="csv-file-input" type="file" accept=".csv,.txt" onChange={onFileChange}
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
        <button data-testid="cancel-csv-btn" type="button" onClick={onCancel}
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
);

const AddPlayerForm = ({ match, teams, playerForm, setPlayerForm, onSubmit, onCancel }) => (
  <div className="bg-[#0A0A0A] border border-white/10 p-6 mb-6">
    <h4 className="text-sm font-bold uppercase tracking-wider text-white mb-3">Add Player</h4>
    <form onSubmit={onSubmit} className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Name *</label>
          <input data-testid="player-name-input" type="text" value={playerForm.name}
            onChange={(e) => setPlayerForm({ ...playerForm, name: e.target.value })}
            className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none" required />
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
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Match Team</label>
          <select data-testid="player-team-select" value={playerForm.team}
            onChange={(e) => setPlayerForm({ ...playerForm, team: e.target.value })}
            className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none">
            <option value="">{match.team_home} (default)</option>
            <option value={match.team_home}>{match.team_home}</option>
            <option value={match.team_away}>{match.team_away}</option>
          </select>
        </div>
      </div>
      {teams.length > 0 && (
        <div>
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Registered Team & Season (optional)</label>
          <select data-testid="player-registered-team-select" value={playerForm.team_id}
            onChange={(e) => setPlayerForm({ ...playerForm, team_id: e.target.value })}
            className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#007AFF] focus:outline-none">
            <option value="">None (match-only player)</option>
            {teams.map(t => <option key={t.id} value={t.id}>{t.name} — {t.season}</option>)}
          </select>
        </div>
      )}
      <div className="flex gap-2">
        <button data-testid="cancel-add-player-btn" type="button" onClick={onCancel}
          className="px-3 py-2 border border-white/10 text-white text-xs hover:bg-[#1F1F1F] transition-colors">Cancel</button>
        <button data-testid="submit-add-player-btn" type="submit"
          className="px-4 py-2 bg-[#007AFF] hover:bg-[#005bb5] text-white text-xs font-bold tracking-wider uppercase transition-colors">Add</button>
      </div>
    </form>
  </div>
);

const PlayerGroup = ({ group, onDelete }) => {
  // Non-mutating sort — avoids reordering the caller's players array on every render.
  const sortedPlayers = [...group.players].sort((a, b) => (a.number || 99) - (b.number || 99));
  return (
  <div>
    <div className="flex items-center gap-2 mb-3">
      <div className="w-3 h-3" style={{ backgroundColor: group.color }} />
      <h4 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">
        {group.label} ({group.players.length})
      </h4>
    </div>
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
      {sortedPlayers.map(player => (
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
          <button data-testid={`delete-player-${player.id}-btn`} onClick={() => onDelete(player.id)}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-[#666] hover:text-[#EF4444]">
            <Trash size={14} />
          </button>
        </div>
      ))}
    </div>
  </div>
  );
};

const RosterSection = ({
  match, players, teams, playerGroups,
  showAddPlayer, setShowAddPlayer,
  showCsvImport, setShowCsvImport,
  playerForm, setPlayerForm,
  csvData, setCsvData, csvTeam, setCsvTeam,
  onAddPlayer, onCsvImport, onFileChange, onDeletePlayer,
}) => (
  <div className="bg-[#141414] border border-white/10 p-8" data-testid="roster-section">
    <div className="flex items-center justify-between mb-6">
      <div className="flex items-center gap-3">
        <Users size={24} className="text-[#007AFF]" />
        <h3 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Player Roster</h3>
        <span className="text-xs text-[#A3A3A3] bg-white/5 px-2 py-1">{players.length} players</span>
      </div>
      <div className="flex gap-2">
        <button data-testid="import-csv-btn" onClick={() => setShowCsvImport(!showCsvImport)}
          className="flex items-center gap-2 px-4 py-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold tracking-wider uppercase">
          <FileText size={16} /> CSV Import
        </button>
        <button data-testid="add-player-btn" onClick={() => setShowAddPlayer(!showAddPlayer)}
          className="flex items-center gap-2 px-4 py-2 bg-[#007AFF] hover:bg-[#005bb5] text-white transition-colors text-xs font-bold tracking-wider uppercase">
          <Plus size={16} weight="bold" /> Add Player
        </button>
      </div>
    </div>

    {showCsvImport && (
      <CsvImportForm match={match}
        csvData={csvData} setCsvData={setCsvData}
        csvTeam={csvTeam} setCsvTeam={setCsvTeam}
        onFileChange={onFileChange} onSubmit={onCsvImport}
        onCancel={() => setShowCsvImport(false)} />
    )}

    {showAddPlayer && (
      <AddPlayerForm match={match} teams={teams}
        playerForm={playerForm} setPlayerForm={setPlayerForm}
        onSubmit={onAddPlayer} onCancel={() => setShowAddPlayer(false)} />
    )}

    {players.length === 0 ? (
      <div className="text-center py-12 border border-dashed border-white/10">
        <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
        <p className="text-[#A3A3A3] mb-1">No players added yet</p>
        <p className="text-xs text-[#666]">Add players manually or import from CSV</p>
      </div>
    ) : (
      <div className="space-y-6">
        {playerGroups.filter(g => g.players.length > 0).map(group => (
          <PlayerGroup key={group.label} group={group} onDelete={onDeletePlayer} />
        ))}
      </div>
    )}
  </div>
);

export default RosterSection;
