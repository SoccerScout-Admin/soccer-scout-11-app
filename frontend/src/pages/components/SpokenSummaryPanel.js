import { useState, useRef } from 'react';
import axios from 'axios';
import { Microphone, Stop, Sparkle, FilmReel, Copy, Check, X, Lightning } from '@phosphor-icons/react';
import { API, getAuthHeader } from '../../App';

/**
 * Post-game spoken summary recorder + Auto-reel-from-voice-key-moments builder.
 * Designed to live at the top of MatchInsights.js so coaches can drop both
 * features the moment they finish reviewing.
 */
const SpokenSummaryPanel = ({ matchId, hasVoiceKeyMoments, onSummaryUpdated }) => {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [polishing, setPolishing] = useState(false);
  const [reelBusy, setReelBusy] = useState(false);
  const [transcript, setTranscript] = useState(null);
  const [reelResult, setReelResult] = useState(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);

  const recRef = useRef(null);
  const chunksRef = useRef([]);

  const startRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = candidates.find((m) => MediaRecorder.isTypeSupported(m)) || '';
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' });
        if (blob.size < 1500) {
          setError('Too short — try recording 30+ seconds.');
          return;
        }
        await uploadRecap(blob, mimeType || 'audio/webm');
      };
      recorder.start();
      recRef.current = recorder;
      setRecording(true);
    } catch (err) {
      setError(
        err.name === 'NotAllowedError'
          ? 'Microphone permission denied.'
          : err.message || 'Recording failed'
      );
    }
  };

  const stopRecording = () => {
    if (!recording || !recRef.current) return;
    setRecording(false);
    try { recRef.current.stop(); } catch (err) { console.warn('[spoken-summary] recorder.stop() failed:', err); }
  };

  const uploadRecap = async (blob, mimeType) => {
    setTranscribing(true);
    setError(null);
    try {
      const ext = mimeType.includes('mp4') ? 'm4a' : 'webm';
      const form = new FormData();
      form.append('audio', blob, `recap.${ext}`);
      const res = await axios.post(
        `${API}/matches/${matchId}/spoken-summary`,
        form,
        { headers: { ...getAuthHeader(), 'Content-Type': 'multipart/form-data' }, timeout: 90000 }
      );
      setTranscript(res.data.transcript);
      onSummaryUpdated?.(res.data.summary);
    } catch (err) {
      setError(err.response?.data?.detail || 'Transcription failed');
    } finally {
      setTranscribing(false);
    }
  };

  const polish = async () => {
    setPolishing(true);
    setError(null);
    try {
      const res = await axios.post(
        `${API}/matches/${matchId}/spoken-summary/polish`,
        {},
        { headers: getAuthHeader(), timeout: 60000 }
      );
      onSummaryUpdated?.(res.data.summary);
      setTranscript(null); // collapse the raw-transcript card now that summary is shown above
    } catch (err) {
      setError(err.response?.data?.detail || 'Polish failed');
    } finally {
      setPolishing(false);
    }
  };

  const buildReel = async () => {
    setReelBusy(true);
    setError(null);
    setReelResult(null);
    try {
      const res = await axios.post(
        `${API}/matches/${matchId}/auto-reel`,
        { pre_seconds: 5, post_seconds: 7 },
        { headers: getAuthHeader() }
      );
      setReelResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Auto-reel failed');
    } finally {
      setReelBusy(false);
    }
  };

  const reelShareUrl = reelResult
    ? `${window.location.origin}/clip-collection/${reelResult.share_token}`
    : '';

  const copyReelLink = async () => {
    if (!reelShareUrl) return;
    try {
      await navigator.clipboard.writeText(reelShareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch (err) { console.warn('[spoken-summary] clipboard.writeText failed:', err); }
  };

  return (
    <div data-testid="spoken-summary-panel"
      className="bg-[#0F0F1A] border border-[#A855F7]/30 p-5 sm:p-6">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A855F7] mb-1">Live coach tools</div>
          <h3 className="text-base sm:text-lg font-bold text-white">Record a spoken recap or auto-build a highlight reel</h3>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {/* Spoken summary recorder */}
        <div className="bg-white/[0.03] border border-white/10 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Microphone size={16} weight="bold" className="text-[#A855F7]" />
            <span className="text-xs font-bold tracking-wider uppercase text-white">Spoken Summary</span>
          </div>
          <p className="text-[11px] text-[#A3A3A3] mb-3 leading-relaxed">Dictate 30-90 seconds of post-game thoughts. We'll save the transcript as the match summary.</p>
          {!recording && !transcribing && !transcript && (
            <button data-testid="start-recap-btn" onClick={startRecording}
              className="w-full bg-[#A855F7] hover:bg-[#9333EA] text-white px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition-colors flex items-center justify-center gap-2">
              <Microphone size={14} weight="fill" /> Start Recording
            </button>
          )}
          {recording && (
            <button data-testid="stop-recap-btn" onClick={stopRecording}
              className="w-full bg-[#EF4444] hover:bg-[#DC2626] text-white px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition-colors flex items-center justify-center gap-2 animate-pulse">
              <Stop size={14} weight="fill" /> Stop & Save
            </button>
          )}
          {transcribing && (
            <div className="w-full bg-[#FBBF24]/15 border border-[#FBBF24]/30 text-[#FBBF24] px-4 py-2.5 text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2">
              <Sparkle size={14} weight="fill" className="animate-pulse" /> Transcribing…
            </div>
          )}
          {transcript && !transcribing && (
            <button data-testid="polish-btn" onClick={polish} disabled={polishing}
              className="w-full bg-[#0EA5E9] hover:bg-[#0284C7] text-white px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition-colors flex items-center justify-center gap-2 disabled:opacity-50">
              {polishing ? (
                <><Sparkle size={14} weight="fill" className="animate-pulse" /> Polishing…</>
              ) : (
                <><Lightning size={14} weight="fill" /> AI polish — clean it up</>
              )}
            </button>
          )}
        </div>

        {/* Auto-reel */}
        <div className="bg-white/[0.03] border border-white/10 p-4">
          <div className="flex items-center gap-2 mb-3">
            <FilmReel size={16} weight="bold" className="text-[#10B981]" />
            <span className="text-xs font-bold tracking-wider uppercase text-white">Auto Highlight Reel</span>
          </div>
          <p className="text-[11px] text-[#A3A3A3] mb-3 leading-relaxed">
            {hasVoiceKeyMoments
              ? "Build a shareable reel from every voice key_moment you tagged during the match."
              : "Tag key moments via the Live Coaching mic in Video Analysis first, then come back."}
          </p>
          {!reelResult && (
            <button data-testid="auto-reel-btn" onClick={buildReel} disabled={reelBusy || !hasVoiceKeyMoments}
              className="w-full bg-[#10B981] hover:bg-[#059669] text-white px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition-colors flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed">
              {reelBusy ? (
                <><Sparkle size={14} weight="fill" className="animate-pulse" /> Building reel…</>
              ) : (
                <><FilmReel size={14} weight="fill" /> Build Reel</>
              )}
            </button>
          )}
          {reelResult && (
            <div data-testid="auto-reel-result" className="bg-[#10B981]/10 border border-[#10B981]/30 p-3">
              <div className="text-[11px] font-bold text-[#10B981] mb-1">{reelResult.clip_count} clips bundled</div>
              <div className="text-[10px] text-[#A3A3A3] truncate mb-2">{reelResult.title}</div>
              <button data-testid="copy-reel-link-btn" onClick={copyReelLink}
                className="w-full text-[10px] uppercase tracking-wider text-white bg-[#10B981] hover:bg-[#059669] px-3 py-1.5 transition-colors flex items-center justify-center gap-1">
                {copied ? <><Check size={11} weight="bold" /> Copied!</> : <><Copy size={11} /> Copy share link</>}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Raw transcript preview (collapsed once polished) */}
      {transcript && !transcribing && (
        <div data-testid="raw-transcript-card" className="mt-3 bg-white/[0.02] border border-white/10 p-3">
          <div className="flex items-start justify-between gap-2 mb-1">
            <span className="text-[10px] font-bold tracking-wider uppercase text-[#666]">Your raw transcript</span>
            <button onClick={() => setTranscript(null)} aria-label="Hide raw transcript"
              className="text-[#666] hover:text-white">
              <X size={12} />
            </button>
          </div>
          <p className="text-xs text-[#CCC] leading-relaxed">{transcript}</p>
        </div>
      )}

      {error && (
        <div data-testid="spoken-summary-error" className="mt-3 bg-[#EF4444]/10 border border-[#EF4444]/30 text-[#EF4444] text-xs px-3 py-2">
          {error}
        </div>
      )}
    </div>
  );
};

export default SpokenSummaryPanel;
