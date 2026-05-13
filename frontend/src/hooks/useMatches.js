/**
 * useMatches
 * ----------
 * Owns matches state + all CRUD/bulk operations + selection mode. Extracted
 * from Dashboard.js during the iter53 refactor.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../App';

export const useMatches = (selectedFolderId) => {
  const [matches, setMatches] = useState([]);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedMatchIds, setSelectedMatchIds] = useState([]);
  const [bulkBusy, setBulkBusy] = useState(false);

  const fetchMatches = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/matches`, { headers: getAuthHeader() });
      setMatches(response.data);
    } catch (err) {
      console.error('Failed to fetch matches:', err);
    }
  }, []);

  useEffect(() => { fetchMatches(); }, [fetchMatches]);

  const toggleMatchSelection = useCallback((id) => {
    setSelectedMatchIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }, []);

  const exitSelectionMode = useCallback(() => {
    setSelectionMode(false);
    setSelectedMatchIds([]);
  }, []);

  const _bulkAction = useCallback(async (endpoint, body, failMsg) => {
    if (selectedMatchIds.length === 0) return;
    setBulkBusy(true);
    try {
      await axios.post(`${API}/matches/bulk/${endpoint}`, { match_ids: selectedMatchIds, ...body }, { headers: getAuthHeader() });
      await fetchMatches();
      setSelectionMode(false);
      setSelectedMatchIds([]);
    } catch (err) {
      alert(`${failMsg}: ${err.response?.data?.detail || err.message}`);
    } finally {
      setBulkBusy(false);
    }
  }, [selectedMatchIds, fetchMatches]);

  const bulkMove = useCallback((folder_id) => _bulkAction('move', { folder_id }, 'Bulk move failed'), [_bulkAction]);

  const bulkSetCompetition = useCallback(() => {
    const comp = window.prompt(
      `Set competition for ${selectedMatchIds.length} selected match${selectedMatchIds.length === 1 ? '' : 'es'}:`,
      ''
    );
    if (comp === null) return Promise.resolve();
    return _bulkAction('competition', { competition: comp }, 'Bulk update failed');
  }, [selectedMatchIds, _bulkAction]);

  const bulkDelete = useCallback(() => {
    const ok = window.confirm(
      `Delete ${selectedMatchIds.length} match${selectedMatchIds.length === 1 ? '' : 'es'}? `
      + 'Their videos enter the 24h restore window. Clips and AI analyses are removed permanently.'
    );
    if (!ok) return Promise.resolve();
    return _bulkAction('delete', {}, 'Bulk delete failed');
  }, [selectedMatchIds, _bulkAction]);

  const createMatch = useCallback(async (formData) => {
    const payload = { ...formData };
    if (selectedFolderId && selectedFolderId !== '__none__') payload.folder_id = selectedFolderId;
    const res = await axios.post(`${API}/matches`, payload, { headers: getAuthHeader() });
    await fetchMatches();
    return res.data;  // {id, team_home, team_away, ...} — caller needs match.id for the roster import step
  }, [selectedFolderId, fetchMatches]);

  const moveMatch = useCallback(async (matchId, folderId) => {
    try {
      await axios.patch(`${API}/matches/${matchId}`, { folder_id: folderId || null }, { headers: getAuthHeader() });
      await fetchMatches();
    } catch (err) {
      console.error('Failed to move match:', err);
    }
  }, [fetchMatches]);

  const deleteMatch = useCallback(async (match) => {
    const confirmMsg = `Delete match "${match.team_home} vs ${match.team_away}"? `
      + (match.video_id
        ? 'The video enters the 24h restore window. Clips and AI analyses are removed permanently.'
        : 'This cannot be undone.');
    if (!window.confirm(confirmMsg)) return;
    try {
      await axios.delete(`${API}/matches/${match.id}`, { headers: getAuthHeader() });
      setMatches((prev) => prev.filter((m) => m.id !== match.id));
    } catch (err) {
      alert(`Failed to delete match: ${err.response?.data?.detail || err.message}`);
    }
  }, []);

  // Apply the active folder filter so the dashboard doesn't need to know the
  // sentinel value semantics ('__none__' = unsorted).
  const displayMatches = useMemo(() => {
    if (selectedFolderId === '__none__') return matches.filter((m) => !m.folder_id);
    if (selectedFolderId) return matches.filter((m) => m.folder_id === selectedFolderId);
    return matches;
  }, [matches, selectedFolderId]);

  return {
    matches,
    displayMatches,
    fetchMatches,
    createMatch,
    moveMatch,
    deleteMatch,
    // selection mode
    selectionMode, setSelectionMode,
    selectedMatchIds, toggleMatchSelection,
    exitSelectionMode,
    // bulk operations
    bulkBusy, bulkMove, bulkSetCompetition, bulkDelete,
  };
};

export default useMatches;
