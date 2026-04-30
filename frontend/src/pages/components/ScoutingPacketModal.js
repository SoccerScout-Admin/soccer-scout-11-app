import { useState } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { FilePdf, X, Download, Info, Spinner } from '@phosphor-icons/react';

/**
 * Admin/owner-gated modal that triggers the backend PDF scouting packet generator.
 * Streams the returned PDF as a browser download. Coach can optionally include
 * a free-text recommendation that becomes page 5 of the packet.
 */
const ScoutingPacketModal = ({ open, onClose, playerId, playerName }) => {
  const [notes, setNotes] = useState('');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await axios.post(
        `${API}/scouting-packets/player/${playerId}`,
        { coach_notes: notes.slice(0, 3000) },
        {
          headers: getAuthHeader(),
          responseType: 'blob',
        },
      );
      // Stream-download
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const fname = `scouting-packet-${(playerName || 'player').replace(/\s+/g, '-').toLowerCase()}.pdf`;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      onClose();
    } catch (err) {
      // Parse error response — it'll be a blob when responseType=blob, convert to text
      let msg = err.response?.data?.detail || err.message || 'Failed to generate packet';
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text();
          const parsed = JSON.parse(text);
          msg = parsed.detail || msg;
        } catch { /* swallow, fall back to generic message */ }
      }
      setError(msg);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div data-testid="packet-modal-overlay" onClick={() => !generating && onClose()}
      className="fixed inset-0 bg-black/80 z-[200] flex items-center justify-center p-4">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#0A0A0A] border border-white/10 w-full max-w-lg">
        <div className="flex items-center justify-between p-5 border-b border-white/10">
          <div className="flex items-center gap-2 min-w-0">
            <FilePdf size={22} weight="bold" className="text-[#10B981] flex-shrink-0" />
            <div className="min-w-0">
              <h3 className="text-lg sm:text-xl font-bold tracking-wider uppercase truncate" style={{ fontFamily: 'Bebas Neue' }}>
                Scouting Packet
              </h3>
              <p className="text-xs text-[#A3A3A3] truncate">for {playerName}</p>
            </div>
          </div>
          <button data-testid="close-packet-modal-btn" onClick={onClose} disabled={generating}
            className="p-2 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] disabled:opacity-50">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          <div className="bg-[#10B981]/10 border border-[#10B981]/30 text-[#10B981] text-xs p-3 flex gap-2">
            <Info size={14} weight="bold" className="flex-shrink-0 mt-0.5" />
            <span className="leading-relaxed">
              A 4-page branded PDF with cover, season stats, performance chart, and clips index (with QR codes).
              Optional coach's recommendation becomes page 5.
            </span>
          </div>

          <div>
            <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">
              Coach's Recommendation (optional)
            </label>
            <textarea data-testid="packet-notes-input"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={6}
              maxLength={3000}
              placeholder="e.g. 'Elite vision in tight spaces. Positional awareness has improved significantly over the season. Ready for a U21 promotion; would thrive in a possession-based system.'"
              className="w-full bg-[#141414] border border-white/10 text-white px-3 py-2 text-sm focus:border-[#10B981] focus:outline-none resize-none" />
            <div className="text-[10px] text-[#555] text-right mt-1">{notes.length}/3000 characters</div>
          </div>

          {error && (
            <div data-testid="packet-error" className="bg-[#1F0E0E] border border-[#EF4444]/30 p-3 text-xs text-[#EF4444]">
              {error}
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-1">
            <span className="text-[10px] text-[#555] tracking-wider uppercase">
              Admin / owner only
            </span>
            <div className="flex gap-2">
              <button type="button" onClick={onClose} disabled={generating}
                className="px-4 py-2.5 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] text-xs font-bold tracking-wider uppercase disabled:opacity-50">
                Cancel
              </button>
              <button data-testid="generate-packet-btn" onClick={handleGenerate} disabled={generating}
                className="flex items-center gap-2 px-5 py-2.5 bg-[#10B981] hover:bg-[#059669] disabled:opacity-50 text-black text-xs font-bold tracking-wider uppercase transition-colors">
                {generating ? (
                  <><Spinner size={14} weight="bold" className="animate-spin" /> Generating…</>
                ) : (
                  <><Download size={14} weight="bold" /> Download PDF</>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ScoutingPacketModal;
