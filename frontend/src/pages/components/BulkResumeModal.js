import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { X, CheckCircle, WarningCircle, Spinner, FilePlus } from '@phosphor-icons/react';

const CHUNK_SIZE = 10 * 1024 * 1024;

/**
 * iter92 — Bulk Resume Picker.
 *
 * After the 2026-05-23 Object Storage outage, your user was left with 13
 * paused uploads. The iter84 "Continue where you left off" banner lets you
 * jump into each match one at a time, re-pick the file, and resume. That's
 * 13 round-trips for a coach who just wants to finish their backlog.
 *
 * This modal lets the user pick ALL 13 files at once via a single
 * <input type="file" multiple>. Files are matched to pending sessions by
 * (filename, exact byte size) — so a coach with two files named
 * "game.mp4" only resumes the one whose bytes actually match. Matched
 * files are queued and uploaded sequentially in the background; the modal
 * shows live per-file progress and a summary when done.
 *
 * Powered by:
 *   - GET /api/me/pending-uploads (list sessions + file_size in bytes)
 *   - POST /api/videos/upload/init (re-bind to existing session; returns
 *     uploaded_chunks so we only re-upload the missing ones)
 *   - POST /api/videos/upload/chunk (existing iter82+iter89 chunk pipeline)
 */

const BulkResumeModal = ({ open, onClose, sessions, onAllComplete }) => {
  const [matches, setMatches] = useState([]);         // [{session, file, status, progress}]
  const [unmatched, setUnmatched] = useState([]);     // [file]
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!open) {
      setMatches([]); setUnmatched([]); setRunning(false); setDone(false);
    }
  }, [open]);

  if (!open) return null;

  const handlePick = (files) => {
    if (!files || files.length === 0) return;
    const arr = Array.from(files);
    const used = new Set();
    const matchedRows = [];
    const unmatchedFiles = [];
    for (const f of arr) {
      const candidate = sessions.find(
        (s) => !used.has(s.upload_id) && s.filename === f.name && s.file_size === f.size,
      );
      if (candidate) {
        used.add(candidate.upload_id);
        matchedRows.push({
          session: candidate,
          file: f,
          status: 'queued',
          progress: candidate.progress_pct || 0,
          error: null,
        });
      } else {
        unmatchedFiles.push(f);
      }
    }
    setMatches(matchedRows);
    setUnmatched(unmatchedFiles);
    setDone(false);
  };

  const uploadOne = async (row, updateRow) => {
    const { session, file } = row;
    try {
      updateRow({ status: 'initializing' });
      // Hit init — server returns existing session + uploaded_chunks
      const initResp = await axios.post(`${API}/videos/upload/init`, {
        match_id: session.match_id,
        filename: file.name,
        file_size: file.size,
        content_type: file.type || 'video/mp4',
      }, { headers: getAuthHeader() });
      const { upload_id, total_chunks: totalChunks, uploaded_chunks: uploadedChunks = [], chunk_size: chunkSize = CHUNK_SIZE } = initResp.data;
      const all = Array.from({ length: totalChunks }, (_, i) => i);
      const toUpload = uploadedChunks.length > 0 ? all.filter((i) => !uploadedChunks.includes(i)) : all;
      let uploadedCount = uploadedChunks.length;

      for (const i of toUpload) {
        const start = i * chunkSize;
        const chunk = file.slice(start, Math.min(start + chunkSize, file.size));
        const form = new FormData();
        form.append('file', chunk);
        // Same retry budget + 503-aware backoff as iter82
        let lastErr = null;
        for (let attempt = 1; attempt <= 20; attempt++) {
          try {
            await axios.post(
              `${API}/videos/upload/chunk?upload_id=${upload_id}&chunk_index=${i}&total_chunks=${totalChunks}`,
              form, { headers: getAuthHeader(), timeout: 300000 },
            );
            lastErr = null;
            break;
          } catch (err) {
            lastErr = err;
            const status = err.response?.status;
            const retryable = !err.response || status >= 500 || err.code === 'ECONNABORTED';
            if (!retryable || attempt === 20) throw err;
            const backoff = Math.min(2000 * Math.pow(2, attempt - 1), 60000);
            updateRow({ status: status === 503 ? 'waiting-storage' : 'retrying' });
            await new Promise((r) => setTimeout(r, backoff));
          }
        }
        if (lastErr) throw lastErr;

        uploadedCount++;
        updateRow({ status: 'uploading', progress: Math.round((uploadedCount / totalChunks) * 100) });
      }
      updateRow({ status: 'done', progress: 100 });
    } catch (err) {
      const reason = err.response?.data?.detail || err.message || 'failed';
      updateRow({ status: 'failed', error: reason });
    }
  };

  const handleStart = async () => {
    setRunning(true);
    // Sequential — one file at a time so we don't slam the storage layer
    // with N parallel multi-chunk uploads.
    for (let idx = 0; idx < matches.length; idx++) {
      // eslint-disable-next-line no-loop-func
      const updateRow = (patch) => setMatches((prev) => prev.map((r, i) => i === idx ? { ...r, ...patch } : r));
      await uploadOne(matches[idx], updateRow);
    }
    setRunning(false);
    setDone(true);
    if (onAllComplete) onAllComplete();
  };

  const matchedDone = matches.filter((m) => m.status === 'done').length;
  const matchedFailed = matches.filter((m) => m.status === 'failed').length;

  return (
    <div data-testid="bulk-resume-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-[#0A0A0A] border border-[#007AFF]/30 w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-white/10 flex-shrink-0">
          <div>
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#007AFF] mb-1">
              Bulk Resume
            </div>
            <h2 className="text-xl font-bold text-white">Finish all paused uploads at once</h2>
            <p className="text-xs text-[#A3A3A3] mt-1">
              Pick {sessions.length} file{sessions.length === 1 ? '' : 's'} from your device. We'll match each one to its waiting session by filename + exact byte size, then resume them sequentially in the background.
            </p>
          </div>
          <button data-testid="bulk-resume-modal-close" onClick={onClose} disabled={running}
            className="text-[#A3A3A3] hover:text-white disabled:opacity-40 disabled:cursor-not-allowed">
            <X size={20} weight="bold" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {matches.length === 0 && unmatched.length === 0 && (
            <button data-testid="bulk-resume-file-picker"
              onClick={() => fileInputRef.current?.click()}
              className="w-full border-2 border-dashed border-[#007AFF]/40 rounded p-8 text-center hover:bg-[#007AFF]/5 transition-colors">
              <FilePlus size={32} weight="bold" className="text-[#007AFF] mx-auto mb-3" />
              <div className="text-sm font-bold text-white">Pick your files</div>
              <div className="text-xs text-[#A3A3A3] mt-1">
                Select up to {sessions.length} files at once. Files that don't match any paused session will be flagged below.
              </div>
            </button>
          )}
          <input ref={fileInputRef} type="file" multiple accept="video/*" className="hidden"
            onChange={(e) => handlePick(e.target.files)} />

          {matches.length > 0 && (
            <div data-testid="bulk-resume-matches" className="space-y-2">
              <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#A3A3A3] mb-1">
                {matches.length} matched · {matchedDone} done · {matchedFailed} failed
              </div>
              {matches.map((m, i) => (
                <div key={m.session.upload_id} data-testid={`bulk-resume-row-${m.session.upload_id}`}
                  className="border border-white/10 px-3 py-2 flex items-center gap-3">
                  <div className="flex-shrink-0 w-6 h-6 flex items-center justify-center">
                    {m.status === 'done' && <CheckCircle size={20} weight="fill" className="text-emerald-500" />}
                    {m.status === 'failed' && <WarningCircle size={20} weight="fill" className="text-red-500" />}
                    {(m.status === 'uploading' || m.status === 'initializing' || m.status === 'retrying' || m.status === 'waiting-storage') &&
                      <Spinner size={20} className="text-[#007AFF] animate-spin" />}
                    {m.status === 'queued' && <span className="text-xs text-[#A3A3A3]">{i + 1}</span>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-bold text-white truncate">{m.session.match_label}</div>
                    <div className="text-xs text-[#A3A3A3] truncate">
                      {m.file.name} · {(m.file.size / (1024 ** 3)).toFixed(2)} GB · {m.progress}%
                      {m.status === 'failed' && <span className="text-red-400"> · {m.error}</span>}
                      {m.status === 'waiting-storage' && <span className="text-yellow-400"> · waiting for storage</span>}
                    </div>
                    {(m.status === 'uploading' || m.progress > 0) && (
                      <div className="h-1 bg-white/10 mt-1 overflow-hidden">
                        <div className="h-full bg-[#007AFF]" style={{ width: `${m.progress}%` }} />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {unmatched.length > 0 && (
            <div data-testid="bulk-resume-unmatched"
              className="border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-300">
              <div className="font-bold mb-1">{unmatched.length} file{unmatched.length === 1 ? '' : 's'} couldn't be matched</div>
              {unmatched.map((f, i) => (
                <div key={i} className="truncate">• {f.name} ({(f.size / (1024 ** 3)).toFixed(2)} GB)</div>
              ))}
              <div className="mt-1 text-yellow-400/70">
                Each file's name AND exact byte size must match a paused session. If you renamed or re-exported the file, the bytes won't line up — start a fresh upload from the match page instead.
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-white/10 px-6 py-3 flex items-center justify-end gap-2 flex-shrink-0">
          {matches.length === 0 ? (
            <button data-testid="bulk-resume-cancel" onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-[#A3A3A3] hover:text-white transition-colors">
              Cancel
            </button>
          ) : !done ? (
            <>
              <button data-testid="bulk-resume-cancel" onClick={onClose} disabled={running}
                className="px-4 py-2 text-xs font-medium text-[#A3A3A3] hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                {running ? 'Uploading — please wait' : 'Cancel'}
              </button>
              <button data-testid="bulk-resume-start" onClick={handleStart} disabled={running || matches.length === 0}
                className="px-5 py-2 bg-[#007AFF] text-white text-xs font-bold tracking-wide uppercase hover:bg-[#0066D6] transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                {running ? 'Uploading…' : `Start ${matches.length} upload${matches.length === 1 ? '' : 's'}`}
              </button>
            </>
          ) : (
            <button data-testid="bulk-resume-close" onClick={onClose}
              className="px-5 py-2 bg-emerald-500/10 text-emerald-400 text-xs font-bold tracking-wide uppercase hover:bg-emerald-500/20 transition-colors">
              Done — close
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default BulkResumeModal;
