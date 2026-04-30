import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../../App';

/**
 * Centralises the processing-status polling loop + server-restart detection
 * for a video.
 *
 * @param {string} videoId
 * @param {(newAnalyses: Array) => void} onAnalysesRefresh  called when processing transitions to completed/failed
 * @param {(newMarkers: Array) => void} onMarkersRefresh
 * @returns {{
 *   processingStatus, serverRestarted,
 *   isProcessing, isProcessed, processingFailed,
 *   reprocess, fetchNow,
 * }}
 */
export const useVideoProcessing = (videoId, onAnalysesRefresh, onMarkersRefresh) => {
  const [processingStatus, setProcessingStatus] = useState(null);
  const [serverBootId, setServerBootId] = useState(null);
  const [serverRestarted, setServerRestarted] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/videos/${videoId}/processing-status`, { headers: getAuthHeader() });
      const data = response.data;
      setProcessingStatus(data);

      if (data.server_boot_id) {
        if (serverBootId && serverBootId !== data.server_boot_id) {
          console.log('Server restarted detected — boot_id changed');
          setServerRestarted(true);
          const res = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
          onAnalysesRefresh?.(res.data);
        }
        setServerBootId(data.server_boot_id);
      }
      return data;
    } catch (err) {
      console.error('Failed to fetch processing status:', err);
      return null;
    }
  }, [videoId, serverBootId, onAnalysesRefresh]);

  // Initial fetch on mount
  useEffect(() => {
    fetchStatus();
  }, [videoId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll every 8s; refresh analyses + markers when processing transitions to terminal state
  useEffect(() => {
    const interval = setInterval(async () => {
      const status = await fetchStatus();
      const wasActive = processingStatus &&
        (processingStatus.processing_status === 'processing' || processingStatus.processing_status === 'queued');
      const nowTerminal = status &&
        (status.processing_status === 'completed' || status.processing_status === 'failed');
      if (status && wasActive && nowTerminal) {
        try {
          const res = await axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() });
          onAnalysesRefresh?.(res.data);
          const mkRes = await axios.get(`${API}/markers/video/${videoId}`, { headers: getAuthHeader() });
          onMarkersRefresh?.(mkRes.data);
        } catch (e) {
          console.error('Failed to refresh after processing transition:', e);
        }
      }
    }, 8000);
    return () => clearInterval(interval);
  }, [fetchStatus, processingStatus, videoId, onAnalysesRefresh, onMarkersRefresh]);

  const reprocess = async () => {
    try {
      await axios.post(`${API}/videos/${videoId}/reprocess`, {}, { headers: getAuthHeader() });
      setProcessingStatus({ processing_status: 'queued', processing_progress: 0 });
    } catch (err) {
      console.error('Reprocess failed:', err);
    }
  };

  const isProcessing = !!processingStatus &&
    (processingStatus.processing_status === 'processing' || processingStatus.processing_status === 'queued');
  const isProcessed = !!processingStatus && processingStatus.processing_status === 'completed';
  const processingFailed = !!processingStatus && processingStatus.processing_status === 'failed';

  return {
    processingStatus,
    serverRestarted,
    isProcessing,
    isProcessed,
    processingFailed,
    reprocess,
    fetchNow: fetchStatus,
  };
};

/**
 * Initial data loader — fetches metadata, analyses, annotations, clips, match,
 * players, markers, and a short-lived video access token on mount.
 */
export const useVideoData = (videoId) => {
  const [videoMetadata, setVideoMetadata] = useState(null);
  const [match, setMatch] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [clips, setClips] = useState([]);
  const [players, setPlayers] = useState([]);
  const [markers, setMarkers] = useState([]);
  const [videoSrc, setVideoSrc] = useState('');

  useEffect(() => {
    const loadData = async () => {
      try {
        const [metaRes, analysesRes, annotationsRes, clipsRes] = await Promise.all([
          axios.get(`${API}/videos/${videoId}/metadata`, { headers: getAuthHeader() }),
          axios.get(`${API}/analysis/video/${videoId}`, { headers: getAuthHeader() }),
          axios.get(`${API}/annotations/video/${videoId}`, { headers: getAuthHeader() }),
          axios.get(`${API}/clips/video/${videoId}`, { headers: getAuthHeader() }),
        ]);
        setVideoMetadata(metaRes.data);
        setAnalyses(analysesRes.data);
        setAnnotations(annotationsRes.data);
        setClips(clipsRes.data);

        if (metaRes.data.match_id) {
          const matchRes = await axios.get(`${API}/matches/${metaRes.data.match_id}`, { headers: getAuthHeader() });
          setMatch(matchRes.data);
          try {
            const playersRes = await axios.get(`${API}/players/match/${metaRes.data.match_id}`, { headers: getAuthHeader() });
            setPlayers(playersRes.data);
          } catch (e) { console.error('Failed to fetch players:', e); }
        }
        try {
          const markersRes = await axios.get(`${API}/markers/video/${videoId}`, { headers: getAuthHeader() });
          setMarkers(markersRes.data);
        } catch (e) { console.error('Failed to fetch markers:', e); }
        try {
          const tokenRes = await axios.get(`${API}/videos/${videoId}/access-token`, { headers: getAuthHeader() });
          setVideoSrc(`${API}/videos/${videoId}?token=${tokenRes.data.token}`);
        } catch (e) {
          console.error('Failed to get video access token:', e);
          setVideoSrc(`${API}/videos/${videoId}`);
        }
      } catch (err) {
        console.error('Failed to load data:', err);
      }
    };
    loadData();
  }, [videoId]);

  return {
    videoMetadata, match, analyses, setAnalyses,
    annotations, setAnnotations, clips, setClips,
    players, markers, setMarkers, videoSrc,
  };
};
