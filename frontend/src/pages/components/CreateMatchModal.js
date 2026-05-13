import { useState, useEffect } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { Users, FileArrowUp, ArrowRight, Check, X } from '@phosphor-icons/react';

/**
 * Two-step Create Match modal.
 *   Step 1 — match details (home/away/date/competition).
 *   Step 2 — roster (import from existing team / paste CSV / skip).
 *
 * Why the roster step exists: AI analysis quality drops dramatically when the
 * model has to guess at player attribution. Adding the roster *before* upload
 * means tactical notes and timeline markers reference real names ("Reyes #7
 * intercepts in midfield") instead of vague placeholders. Coaches asked for
 * this on 2026-05-13 after running a match through AI with no roster context.
 *
 * Skipping is supported — the video page surfaces an "Awaiting roster" banner
 * if a video is later uploaded against a match with no players, so coaches can
 * still add the roster after the fact (or click "Run anyway" to override).
 */
const CreateMatchModal = ({ open, onClose, onSubmit, formData, setFormData, loading }) => {
  const [step, setStep] = useState('details');  // 'details' | 'roster'
  const [createdMatch, setCreatedMatch] = useState(null);
  const [teams, setTeams] = useState([]);
  const [selectedTeamId, setSelectedTeamId] = useState('');
  const [importBusy, setImportBusy] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [csvText, setCsvText] = useState('');
  const [csvBusy, setCsvBusy] = useState(false);
  const [csvResult, setCsvResult] = useState(null);
  const [rosterMode, setRosterMode] = useState('team');  // 'team' | 'csv' | 'skip'

  useEffect(() => {
    if (!open) return undefined;
    // Reset on each open
    setStep('details');
    setCreatedMatch(null);
    setSelectedTeamId('');
    setImportResult(null);
    setCsvText('');
    setCsvResult(null);
    setRosterMode('team');

    let cancelled = false;
    axios.get(`${API}/teams`, { headers: getAuthHeader() })
      .then((res) => { if (!cancelled) setTeams(res.data || []); })
      .catch(() => { /* silent — coach may have zero teams yet */ });
    return () => { cancelled = true; };
  }, [open]);

  if (!open) return null;

  const handleDetailsSubmit = async (e) => {
    e.preventDefault();
    // Re-use the parent's create handler but capture the returned match for step 2.
    const match = await onSubmit(e, { keepOpen: true });
    if (match?.id) {
      setCreatedMatch(match);
      setStep('roster');
    }
  };

  const handleImportTeamRoster = async () => {
    if (!selectedTeamId || !createdMatch?.id) return;
    setImportBusy(true);
    setImportResult(null);
    try {
      const res = await axios.post(
        `${API}/matches/${createdMatch.id}/import-team-roster`,
        { team_id: selectedTeamId },
        { headers: getAuthHeader() },
      );
      setImportResult(res.data);
    } catch (err) {
      setImportResult({ error: err.response?.data?.detail || 'Import failed' });
    } finally {
      setImportBusy(false);
    }
  };

  const handleCsvImport = async () => {
    if (!csvText.trim() || !createdMatch?.id) return;
    setCsvBusy(true);
    setCsvResult(null);
    try {
      const res = await axios.post(
        `${API}/players/import-csv`,
        { match_id: createdMatch.id, csv_data: csvText },
        { headers: getAuthHeader() },
      );
      setCsvResult({ imported: res.data?.imported ?? 0 });
    } catch (err) {
      setCsvResult({ error: err.response?.data?.detail || 'CSV import failed' });
    } finally {
      setCsvBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/80 overflow-y-auto z-50 p-4 sm:p-6" data-testid="create-match-modal">
      <div className="bg-[#141414] border border-white/10 w-full max-w-lg p-6 sm:p-8 mx-auto my-4 sm:my-8">

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-6 text-[10px] tracking-[0.3em] uppercase">
          <span className={step === 'details' ? 'text-[#007AFF] font-bold' : 'text-[#666]'}>1 · Match</span>
          <ArrowRight size={10} className="text-[#666]" />
          <span className={step === 'roster' ? 'text-[#007AFF] font-bold' : 'text-[#666]'}>2 · Roster</span>
          <button
            type="button"
            onClick={onClose}
            data-testid="close-create-match-modal"
            className="ml-auto p-1 hover:bg-white/5 transition-colors"
            aria-label="Close">
            <X size={14} className="text-[#A3A3A3]" />
          </button>
        </div>

        {step === 'details' && (
          <>
            <h3 className="text-3xl font-bold mb-6" style={{ fontFamily: 'Bebas Neue' }}>Create New Match</h3>
            <form onSubmit={handleDetailsSubmit} className="space-y-4">
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
                <button data-testid="cancel-create-btn" type="button" onClick={onClose}
                  className="flex-1 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
                  Cancel
                </button>
                <button data-testid="submit-create-btn" type="submit" disabled={loading}
                  className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
                  {loading ? 'Creating…' : 'Next · Add Roster'}
                </button>
              </div>
            </form>
          </>
        )}

        {step === 'roster' && createdMatch && (
          <>
            <h3 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Add Roster</h3>
            <p className="text-xs text-[#A3A3A3] mb-5">
              Adding players now means AI analyses reference real names ("Reyes #7") instead of placeholders.
              You can skip and add them later — uploads will pause until a roster exists.
            </p>

            {/* Mode tabs */}
            <div className="grid grid-cols-3 gap-2 mb-5 border-b border-white/5">
              <button
                type="button"
                data-testid="roster-mode-team"
                onClick={() => setRosterMode('team')}
                className={`pb-2 text-[10px] tracking-[0.2em] uppercase font-bold transition-colors ${
                  rosterMode === 'team' ? 'text-[#007AFF] border-b-2 border-[#007AFF]' : 'text-[#A3A3A3] hover:text-white'
                }`}>
                <Users size={14} className="inline mr-1" weight="bold" />
                Existing Team
              </button>
              <button
                type="button"
                data-testid="roster-mode-csv"
                onClick={() => setRosterMode('csv')}
                className={`pb-2 text-[10px] tracking-[0.2em] uppercase font-bold transition-colors ${
                  rosterMode === 'csv' ? 'text-[#007AFF] border-b-2 border-[#007AFF]' : 'text-[#A3A3A3] hover:text-white'
                }`}>
                <FileArrowUp size={14} className="inline mr-1" weight="bold" />
                Paste CSV
              </button>
              <button
                type="button"
                data-testid="roster-mode-skip"
                onClick={() => setRosterMode('skip')}
                className={`pb-2 text-[10px] tracking-[0.2em] uppercase font-bold transition-colors ${
                  rosterMode === 'skip' ? 'text-[#A3A3A3] border-b-2 border-[#A3A3A3]' : 'text-[#666] hover:text-[#A3A3A3]'
                }`}>
                Skip for now
              </button>
            </div>

            {rosterMode === 'team' && (
              <div className="space-y-4" data-testid="roster-team-panel">
                {teams.length === 0 ? (
                  <p className="text-xs text-[#A3A3A3] py-4">
                    No teams yet. Create one under <span className="text-white">Clubs &amp; Teams</span> first, or paste a CSV roster instead.
                  </p>
                ) : (
                  <>
                    <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Pick a team</label>
                    <select
                      data-testid="import-team-select"
                      value={selectedTeamId}
                      onChange={(e) => { setSelectedTeamId(e.target.value); setImportResult(null); }}
                      className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none">
                      <option value="">— Select team —</option>
                      {teams.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name} · {t.season} {t.player_count ? `(${t.player_count} players)` : '(no players)'}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      data-testid="import-team-btn"
                      onClick={handleImportTeamRoster}
                      disabled={!selectedTeamId || importBusy}
                      className="w-full bg-[#10B981] hover:bg-[#0e9d6c] text-black py-3 font-bold tracking-wider uppercase text-xs transition-colors disabled:opacity-40">
                      {importBusy ? 'Importing…' : 'Import Roster'}
                    </button>
                    {importResult && !importResult.error && (
                      <div data-testid="import-result" className="flex items-center gap-2 text-xs text-[#10B981] bg-[#10B981]/10 border border-[#10B981]/30 p-3">
                        <Check size={14} weight="bold" />
                        <span>
                          Imported {importResult.imported} player{importResult.imported !== 1 ? 's' : ''} from {importResult.team_name}
                          {importResult.skipped > 0 && ` (${importResult.skipped} already on this match)`}
                        </span>
                      </div>
                    )}
                    {importResult?.error && (
                      <p data-testid="import-error" className="text-xs text-[#EF4444]">{importResult.error}</p>
                    )}
                  </>
                )}
              </div>
            )}

            {rosterMode === 'csv' && (
              <div className="space-y-3" data-testid="roster-csv-panel">
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">Paste CSV — first row must be header</label>
                <textarea
                  data-testid="roster-csv-textarea"
                  value={csvText}
                  onChange={(e) => { setCsvText(e.target.value); setCsvResult(null); }}
                  rows={6}
                  placeholder={"name,number,position\nReyes,7,Forward\nMurphy,8,Midfielder\nChen,1,Goalkeeper"}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none font-mono text-xs" />
                <button
                  type="button"
                  data-testid="csv-import-btn"
                  onClick={handleCsvImport}
                  disabled={!csvText.trim() || csvBusy}
                  className="w-full bg-[#10B981] hover:bg-[#0e9d6c] text-black py-3 font-bold tracking-wider uppercase text-xs transition-colors disabled:opacity-40">
                  {csvBusy ? 'Importing…' : 'Import CSV'}
                </button>
                {csvResult && !csvResult.error && (
                  <div data-testid="csv-result" className="flex items-center gap-2 text-xs text-[#10B981] bg-[#10B981]/10 border border-[#10B981]/30 p-3">
                    <Check size={14} weight="bold" />
                    <span>Imported {csvResult.imported} players</span>
                  </div>
                )}
                {csvResult?.error && (
                  <p data-testid="csv-error" className="text-xs text-[#EF4444]">{csvResult.error}</p>
                )}
              </div>
            )}

            {rosterMode === 'skip' && (
              <div className="bg-[#FBBF24]/5 border border-[#FBBF24]/20 p-4 text-xs text-[#CFCFCF] leading-relaxed" data-testid="roster-skip-panel">
                <p className="font-bold text-[#FBBF24] mb-2 tracking-[0.15em] uppercase text-[10px]">Heads up</p>
                <p>
                  You can finish the match without a roster. If you upload film later, the video will pause at "Awaiting roster" —
                  add players from the match detail page (or click <span className="text-white">Run anyway</span> to start AI without
                  player attribution).
                </p>
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                type="button"
                data-testid="back-to-details-btn"
                onClick={() => setStep('details')}
                className="px-5 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors text-xs">
                Back
              </button>
              <button
                type="button"
                data-testid="finish-create-match-btn"
                onClick={onClose}
                className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors text-xs">
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default CreateMatchModal;
