/**
 * useFolders
 * -----------
 * Owns folder list state + all CRUD/share operations. Extracted from Dashboard.js
 * during the iter53 refactor — the dashboard had 12+ handlers inline, making it
 * tough to scan. This hook isolates the folder concerns so the dashboard
 * component becomes a render-focused shell.
 *
 * Returns:
 *   folders, expandedFolders, toggleFolderExpand,
 *   fetchFolders, createOrUpdateFolder, deleteFolder,
 *   toggleShare, revokeShare,
 *   flatFolderList(memoized), getShareUrl
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../App';

export const useFolders = () => {
  const [folders, setFolders] = useState([]);
  const [expandedFolders, setExpandedFolders] = useState({});

  const fetchFolders = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/folders`, { headers: getAuthHeader() });
      setFolders(response.data);
      const expanded = {};
      response.data.forEach((f) => { expanded[f.id] = true; });
      setExpandedFolders((prev) => ({ ...expanded, ...prev }));
    } catch (err) {
      console.error('Failed to fetch folders:', err);
    }
  }, []);

  useEffect(() => { fetchFolders(); }, [fetchFolders]);

  const toggleFolderExpand = useCallback((folderId) => {
    setExpandedFolders((prev) => ({ ...prev, [folderId]: !prev[folderId] }));
  }, []);

  const createOrUpdateFolder = useCallback(async ({ editingFolder, folderFormData, selectedFolderId }) => {
    const payload = { ...folderFormData };
    if (!payload.parent_id) delete payload.parent_id;
    if (editingFolder) {
      await axios.patch(`${API}/folders/${editingFolder.id}`, payload, { headers: getAuthHeader() });
    } else {
      if (selectedFolderId && selectedFolderId !== '__none__' && !payload.parent_id) {
        payload.parent_id = selectedFolderId;
      }
      await axios.post(`${API}/folders`, payload, { headers: getAuthHeader() });
    }
    await fetchFolders();
  }, [fetchFolders]);

  const deleteFolder = useCallback(async (folderId, onCleared) => {
    if (!window.confirm('Delete this folder? Matches will move to parent.')) return;
    try {
      await axios.delete(`${API}/folders/${folderId}`, { headers: getAuthHeader() });
      if (onCleared) onCleared(folderId);
      await fetchFolders();
    } catch (err) {
      console.error('Failed to delete folder:', err);
    }
  }, [fetchFolders]);

  const toggleShare = useCallback(async (folder) => {
    if (folder.share_token) return folder; // caller opens the modal directly
    const res = await axios.post(`${API}/folders/${folder.id}/share`, {}, { headers: getAuthHeader() });
    setFolders((prev) => prev.map((f) => (f.id === folder.id ? { ...f, share_token: res.data.share_token } : f)));
    return { ...folder, share_token: res.data.share_token };
  }, []);

  const revokeShare = useCallback(async (folder) => {
    await axios.post(`${API}/folders/${folder.id}/share`, {}, { headers: getAuthHeader() });
    setFolders((prev) => prev.map((f) => (f.id === folder.id ? { ...f, share_token: null } : f)));
  }, []);

  /**
   * Flat depth-first folder list with `depth`, `hasChildren`, `isExpanded` —
   * the shape FolderSidebar expects. Memoized so we don't reflatten on every
   * keystroke when the user is editing something unrelated.
   */
  const flatFolderList = useMemo(() => {
    const result = [];
    const addChildren = (parentId, depth) => {
      const children = folders
        .filter((f) => (f.parent_id || null) === parentId)
        .sort((a, b) => a.name.localeCompare(b.name));
      for (const folder of children) {
        const hasChildren = folders.some((f) => f.parent_id === folder.id);
        const isExpanded = expandedFolders[folder.id] !== false;
        result.push({ ...folder, depth, hasChildren, isExpanded });
        if (hasChildren && isExpanded) addChildren(folder.id, depth + 1);
      }
    };
    addChildren(null, 0);
    return result;
  }, [folders, expandedFolders]);

  return {
    folders,
    expandedFolders,
    flatFolderList,
    fetchFolders,
    toggleFolderExpand,
    createOrUpdateFolder,
    deleteFolder,
    toggleShare,
    revokeShare,
  };
};

export default useFolders;
