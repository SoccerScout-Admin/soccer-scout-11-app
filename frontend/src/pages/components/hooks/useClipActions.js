import { useState } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../../App';

const fallbackCopy = (text) => {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
};

export const useClipShare = (setClips) => {
  const [sharingClip, setSharingClip] = useState(null);
  const [clipShareCopied, setClipShareCopied] = useState(false);

  const handleShareClip = async (clip) => {
    if (clip.share_token) {
      setSharingClip(clip);
      return;
    }
    try {
      const res = await axios.post(`${API}/clips/${clip.id}/share`, {}, { headers: getAuthHeader() });
      if (res.data.share_token) {
        const updated = { ...clip, share_token: res.data.share_token };
        setSharingClip(updated);
        setClips(prev => prev.map(c => c.id === clip.id ? { ...c, share_token: res.data.share_token } : c));
      }
    } catch {
      alert('Failed to generate share link');
    }
  };

  const handleRevokeClipShare = async () => {
    if (!sharingClip) return;
    try {
      await axios.post(`${API}/clips/${sharingClip.id}/share`, {}, { headers: getAuthHeader() });
      setClips(prev => prev.map(c => c.id === sharingClip.id ? { ...c, share_token: null } : c));
      setSharingClip(null);
    } catch {
      alert('Failed to revoke share link');
    }
  };

  const copyClipShareLink = () => {
    if (!sharingClip) return;
    const url = `${window.location.origin}/api/og/clip/${sharingClip.share_token}`;
    const markCopied = () => {
      setClipShareCopied(true);
      setTimeout(() => setClipShareCopied(false), 2000);
    };
    try {
      navigator.clipboard.writeText(url).then(markCopied).catch(() => {
        fallbackCopy(url);
        markCopied();
      });
    } catch (e) {
      console.error('Clipboard copy failed:', e);
    }
  };

  const shareClipTo = (platform) => {
    if (!sharingClip) return;
    const url = `${window.location.origin}/api/og/clip/${sharingClip.share_token}`;
    const text = `${sharingClip.title} — Soccer Scout`;
    if (platform === 'instagram' || platform === 'youtube') {
      copyClipShareLink();
      return;
    }
    const links = {
      facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
      sms: `sms:?body=${encodeURIComponent(`${text}: ${url}`)}`,
    };
    window.open(links[platform], '_blank', 'width=600,height=400');
  };

  return { sharingClip, setSharingClip, clipShareCopied, handleShareClip, handleRevokeClipShare, copyClipShareLink, shareClipTo };
};

export const useClipCollection = (selectedClips, mentionedCoaches) => {
  const [collectionShare, setCollectionShare] = useState(null);
  const [collectionModalOpen, setCollectionModalOpen] = useState(false);
  const [collectionTitle, setCollectionTitle] = useState('');
  const [collectionDescription, setCollectionDescription] = useState('');
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [collectionCopied, setCollectionCopied] = useState(false);

  const handleCreateCollection = async () => {
    if (selectedClips.length === 0) return;
    setCreatingCollection(true);
    try {
      const res = await axios.post(`${API}/clip-collections`, {
        clip_ids: selectedClips,
        title: collectionTitle.trim() || `${selectedClips.length} Clips`,
        description: (collectionDescription || '').trim(),
        mentioned_coach_ids: mentionedCoaches.map((c) => c.id),
      }, { headers: getAuthHeader() });
      setCollectionShare(res.data);
    } catch (err) {
      alert('Failed to create reel: ' + (err.response?.data?.detail || err.message));
    } finally {
      setCreatingCollection(false);
    }
  };

  const collectionUrl = collectionShare
    ? `${window.location.origin}/api/og/clip-collection/${collectionShare.share_token}`
    : '';

  const copyCollectionUrl = async () => {
    if (!collectionUrl) return;
    try {
      await navigator.clipboard.writeText(collectionUrl);
    } catch {
      fallbackCopy(collectionUrl);
    }
    setCollectionCopied(true);
    setTimeout(() => setCollectionCopied(false), 2000);
  };

  return {
    collectionShare, setCollectionShare,
    collectionModalOpen, setCollectionModalOpen,
    collectionTitle, setCollectionTitle,
    collectionDescription, setCollectionDescription,
    creatingCollection, collectionCopied,
    collectionUrl, handleCreateCollection, copyCollectionUrl,
  };
};

export const useClipTagging = (setClips) => {
  const [taggingClip, setTaggingClip] = useState(null);
  const [tagSearch, setTagSearch] = useState('');
  const [tagSelection, setTagSelection] = useState([]);
  const [savingTags, setSavingTags] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState(null);

  const openTagModal = (clip) => {
    setTaggingClip(clip);
    setTagSelection(clip.player_ids || []);
    setTagSearch('');
    setAiSuggestions(null);
  };

  const handleAiSuggest = async () => {
    if (!taggingClip) return;
    setAiSuggesting(true);
    try {
      const res = await axios.post(`${API}/clips/${taggingClip.id}/ai-suggest-tags`, {}, { headers: getAuthHeader() });
      setAiSuggestions(res.data);
      const ids = Array.from(new Set([...tagSelection, ...res.data.suggestions.map(s => s.player_id)]));
      setTagSelection(ids);
    } catch (err) {
      alert('AI tagging failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setAiSuggesting(false);
    }
  };

  const toggleTag = (playerId) => {
    setTagSelection(prev => prev.includes(playerId) ? prev.filter(id => id !== playerId) : [...prev, playerId]);
  };

  const saveClipTags = async () => {
    if (!taggingClip) return;
    setSavingTags(true);
    try {
      await axios.patch(`${API}/clips/${taggingClip.id}`, { player_ids: tagSelection }, { headers: getAuthHeader() });
      setClips(prev => prev.map(c => c.id === taggingClip.id ? { ...c, player_ids: tagSelection } : c));
      setTaggingClip(null);
    } catch (err) {
      alert('Failed to save tags: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSavingTags(false);
    }
  };

  return {
    taggingClip, setTaggingClip, tagSearch, setTagSearch,
    tagSelection, savingTags, aiSuggesting, aiSuggestions,
    openTagModal, handleAiSuggest, toggleTag, saveClipTags,
  };
};
