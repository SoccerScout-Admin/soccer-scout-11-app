import { useState, useRef, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Microphone, Stop, Lightning, Crosshair, Sparkle, X } from '@phosphor-icons/react';
import { API, getAuthHeader } from '../../App';

/**
 * Live Coaching mic — captures sideline audio via MediaRecorder, sends to /voice-annotations,
 * which transcribes via Whisper + classifies via Gemini and returns a fully-formed annotation.
 *
 * Two render modes:
 *   - FAB (mobile): bottom-right floating action button, press-and-hold to record
 *   - Inline (desktop): toolbar pill button next to the existing tactical/note tools
 *
 * Live mode toggle: when ON, drops the new annotation at `liveAnchorTimestamp + elapsedSinceAnchor`
 * (instead of `video.currentTime`), so coaches can tag plays in real-time without scrubbing.
 */
const LiveCoachingMic = ({
  videoId,
  videoCurrentTime = 0,
  isMobile = false,
  onAnnotationAdded,
}) => {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState(null);
  const [liveMode, setLiveMode] = useState(false);
  const [liveAnchorMs, setLiveAnchorMs] = useState(null); // wall-clock ms at toggle-on
  const [liveAnchorVideoTime, setLiveAnchorVideoTime] = useState(0); // video time at toggle-on
  const [recentTags, setRecentTags] = useState([]);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  // Cleanup any active recorder on unmount
  useEffect(() => () => {
    try {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
    } catch { /* noop */ }
  }, []);

  const computeTimestamp = useCallback(() => {
    if (liveMode && liveAnchorMs != null) {
      const elapsedSec = (Date.now() - liveAnchorMs) / 1000;
      return liveAnchorVideoTime + elapsedSec;
    }
    return videoCurrentTime;
  }, [liveMode, liveAnchorMs, liveAnchorVideoTime, videoCurrentTime]);

  const toggleLiveMode = () => {
    if (liveMode) {
      setLiveMode(false);
      setLiveAnchorMs(null);
    } else {
      setLiveMode(true);
      setLiveAnchorMs(Date.now());
      setLiveAnchorVideoTime(videoCurrentTime);
    }
  };

  const startRecording = async () => {
    if (recording || transcribing) return;
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Pick the best mime type the browser supports
      const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = candidates.find((m) => MediaRecorder.isTypeSupported(m)) || '';
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        // Stop all tracks immediately so the browser mic indicator goes away
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: mimeType || 'audio/webm' });
        if (blob.size < 1500) {
          setError('Recording too short — hold for ≥1 second');
          return;
        }
        await uploadAndProcess(blob, mimeType || 'audio/webm');
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecording(true);
    } catch (err) {
      const detail = err.name === 'NotAllowedError'
        ? 'Microphone permission denied. Enable in browser settings.'
        : err.message || 'Failed to start recording';
      setError(detail);
    }
  };

  const stopRecording = () => {
    if (!recording || !mediaRecorderRef.current) return;
    setRecording(false);
    try { mediaRecorderRef.current.stop(); } catch { /* noop */ }
  };

  const uploadAndProcess = async (blob, mimeType) => {
    setTranscribing(true);
    const ts = computeTimestamp();
    try {
      const ext = mimeType.includes('mp4') ? 'm4a' : 'webm';
      const form = new FormData();
      form.append('video_id', videoId);
      form.append('timestamp', String(ts));
      form.append('audio', blob, `voice.${ext}`);

      const res = await axios.post(`${API}/voice-annotations`, form, {
        headers: { ...getAuthHeader(), 'Content-Type': 'multipart/form-data' },
        timeout: 60000,
      });
      const ann = res.data;
      onAnnotationAdded?.(ann);
      setRecentTags((prev) => [ann, ...prev].slice(0, 3));
    } catch (err) {
      setError(err.response?.data?.detail || 'Transcription failed');
    } finally {
      setTranscribing(false);
      setTimeout(() => setError(null), 6000);
    }
  };

  const dismissRecent = (id) => {
    setRecentTags((prev) => prev.filter((t) => t.id !== id));
  };

  // Status text for the button label
  const statusText = transcribing ? 'Transcribing...' : recording ? 'Recording...' : 'Hold to tag';

  // Color theme — red while recording, blue while idle, purple when in live mode
  const colorClass = recording
    ? 'bg-[#EF4444] text-white'
    : transcribing
    ? 'bg-[#FBBF24] text-black'
    : liveMode
    ? 'bg-[#A855F7] text-white'
    : 'bg-[#007AFF] text-white';

  // Pointer events: hold-to-record on mobile FAB; click-to-toggle on desktop (also press-hold supported)
  const pointerHandlers = {
    onPointerDown: (e) => { e.preventDefault(); startRecording(); },
    onPointerUp: (e) => { e.preventDefault(); stopRecording(); },
    onPointerLeave: () => { if (recording) stopRecording(); },
    onPointerCancel: () => { if (recording) stopRecording(); },
  };

  if (isMobile) {
    return (
      <>
        {/* FAB (mobile) */}
        <div className="fixed bottom-6 right-6 z-[120] flex flex-col items-end gap-3" data-testid="live-coaching-fab">
          {/* Live mode toggle pill (only shows when recently used or live mode is on) */}
          <button data-testid="live-mode-toggle"
            onClick={toggleLiveMode}
            aria-label={liveMode ? 'Disable live mode' : 'Enable live mode'}
            className={`text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 border transition-colors flex items-center gap-1 ${
              liveMode
                ? 'bg-[#A855F7]/15 text-[#A855F7] border-[#A855F7]/40'
                : 'bg-[#0A0A0A]/80 text-[#A3A3A3] border-white/15'
            }`}>
            <Lightning size={10} weight={liveMode ? 'fill' : 'regular'} />
            {liveMode ? 'Live On' : 'Live Off'}
          </button>

          <button
            data-testid="live-mic-btn"
            aria-label="Hold to record voice annotation"
            {...pointerHandlers}
            disabled={transcribing}
            className={`w-16 h-16 rounded-full shadow-[0_8px_24px_rgba(0,0,0,0.6)] flex items-center justify-center transition-all ${colorClass} ${recording ? 'scale-110' : 'scale-100'} disabled:opacity-60`}>
            {transcribing ? (
              <Sparkle size={26} weight="fill" className="animate-pulse" />
            ) : recording ? (
              <Stop size={26} weight="fill" />
            ) : (
              <Microphone size={26} weight="fill" />
            )}
          </button>
        </div>

        {/* Status / error toasts (mobile) */}
        {(recording || transcribing || error) && (
          <div data-testid="live-mic-status"
            className="fixed bottom-28 right-6 z-[121] max-w-[260px] bg-[#0A0A0A] border border-white/15 px-3 py-2 text-xs text-white shadow-lg">
            {error ? (
              <span className="text-[#EF4444]">{error}</span>
            ) : recording ? (
              <span className="flex items-center gap-2"><span className="w-2 h-2 bg-[#EF4444] rounded-full animate-pulse" />Recording — release to transcribe</span>
            ) : (
              <span className="flex items-center gap-2"><Sparkle size={12} weight="fill" className="text-[#FBBF24]" />Whisper + Gemini classify…</span>
            )}
          </div>
        )}

        {/* Recent voice tags toast */}
        {recentTags.length > 0 && !recording && !transcribing && (
          <div className="fixed bottom-28 right-6 z-[120] flex flex-col gap-1.5 items-end">
            {recentTags.slice(0, 1).map((t) => (
              <div key={t.id} data-testid={`live-recent-tag-${t.id}`}
                className="bg-[#0A0A0A] border border-[#A855F7]/40 px-3 py-2 text-xs max-w-[280px] flex items-start gap-2">
                <Crosshair size={14} weight="bold" className="text-[#A855F7] flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="text-[9px] font-bold tracking-wider uppercase text-[#A855F7]">{t.annotation_type}</div>
                  <div className="text-white truncate">{t.content}</div>
                </div>
                <button onClick={() => dismissRecent(t.id)} aria-label="Dismiss" className="text-[#666] hover:text-white">
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </>
    );
  }

  // Inline (desktop) — pill button + live toggle
  return (
    <div className="flex items-center gap-2" data-testid="live-coaching-inline">
      <button data-testid="live-mode-toggle"
        type="button"
        onClick={toggleLiveMode}
        title={liveMode ? 'Live mode: timestamps drop at wall-clock-relative-to-anchor' : 'Click to anchor live mode at current playback'}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider border transition-colors ${
          liveMode
            ? 'bg-[#A855F7]/15 text-[#A855F7] border-[#A855F7]/40'
            : 'bg-transparent text-[#A3A3A3] border-white/15 hover:border-[#A855F7]/40 hover:text-[#A855F7]'
        }`}>
        <Lightning size={11} weight={liveMode ? 'fill' : 'regular'} />
        {liveMode ? 'Live' : 'Live Off'}
      </button>
      <button
        data-testid="live-mic-btn"
        type="button"
        {...pointerHandlers}
        disabled={transcribing}
        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold uppercase tracking-wider transition-all ${colorClass} ${recording ? 'shadow-[0_0_0_3px_rgba(239,68,68,0.3)]' : ''} disabled:opacity-60`}>
        {transcribing ? <Sparkle size={12} weight="fill" className="animate-pulse" /> : recording ? <Stop size={12} weight="fill" /> : <Microphone size={12} weight="fill" />}
        {statusText}
      </button>
      {error && <span data-testid="live-mic-error" className="text-[10px] text-[#EF4444] ml-1">{error}</span>}
    </div>
  );
};

export default LiveCoachingMic;
