import { useState, useRef } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import {
  X, UploadSimple, FileCsv, CheckCircle, Warning, DownloadSimple, ArrowsClockwise,
} from '@phosphor-icons/react';

const RosterImportModal = ({ teamId, teamName, onClose, onImported }) => {
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [preview, setPreview] = useState(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setError('');
    if (inputRef.current) inputRef.current.value = '';
  };

  const onFileSelected = async (selected) => {
    if (!selected) return;
    setFile(selected);
    setError('');
    setPreview(null);

    const fd = new FormData();
    fd.append('file', selected);
    try {
      const res = await axios.post(
        `${API}/teams/${teamId}/players/import?dry_run=true`,
        fd,
        { headers: { ...getAuthHeader(), 'Content-Type': 'multipart/form-data' } },
      );
      setPreview(res.data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not parse file. Make sure it has a "name" column.');
    }
  };

  const onConfirm = async () => {
    if (!file) return;
    setImporting(true);
    setError('');
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await axios.post(
        `${API}/teams/${teamId}/players/import`,
        fd,
        { headers: { ...getAuthHeader(), 'Content-Type': 'multipart/form-data' } },
      );
      onImported(res.data);
      onClose();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Import failed. Please try again.');
    } finally {
      setImporting(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) onFileSelected(e.dataTransfer.files[0]);
  };

  return (
    <div data-testid="roster-import-modal"
      className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center overflow-y-auto"
      onClick={onClose}>
      <div className="bg-[#141414] border border-white/10 max-w-2xl w-full mx-auto my-8 mx-4"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h3 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Import Roster</h3>
            <p className="text-xs text-[#A3A3A3]">Bulk-add players to <span className="text-white">{teamName}</span></p>
          </div>
          <button data-testid="close-import-modal" onClick={onClose}
            className="p-2 hover:bg-[#1F1F1F] transition-colors">
            <X size={20} className="text-[#A3A3A3]" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          {!preview && !file && (
            <>
              <div data-testid="dropzone"
                onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                className={`border-2 border-dashed cursor-pointer p-10 text-center transition-colors ${
                  dragActive ? 'border-[#10B981] bg-[#10B981]/5' : 'border-white/15 hover:border-white/30 hover:bg-[#1A1A1A]'
                }`}>
                <UploadSimple size={48} className="text-[#A3A3A3] mx-auto mb-3" />
                <p className="text-base text-white font-medium mb-1">Drop your CSV file here</p>
                <p className="text-xs text-[#A3A3A3]">or click to browse</p>
                <input ref={inputRef} data-testid="roster-file-input"
                  type="file" accept=".csv,text/csv"
                  onChange={(e) => onFileSelected(e.target.files?.[0])} className="hidden" />
              </div>

              <div className="bg-[#0A0A0A] border border-white/10 p-5">
                <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">CSV Format</p>
                <p className="text-sm text-[#CFCFCF] mb-3">
                  Your file should have a header row with at least a <span className="text-white font-mono bg-[#1F1F1F] px-1.5 py-0.5">name</span> column.
                  Optional: <span className="text-white font-mono bg-[#1F1F1F] px-1.5 py-0.5">number</span> and <span className="text-white font-mono bg-[#1F1F1F] px-1.5 py-0.5">position</span>.
                </p>
                <pre className="bg-[#1F1F1F] text-xs text-[#A3A3A3] p-3 overflow-x-auto font-mono leading-relaxed">{`name,number,position
Jane Doe,9,ST
Maria Lopez,4,CB
Sam Lee,10,CM`}</pre>
                <a href={`${API}/players/import-template.csv`} download
                  data-testid="download-template-btn"
                  className="inline-flex items-center gap-1.5 mt-3 text-xs text-[#10B981] hover:text-[#0EA975] font-bold uppercase tracking-wider">
                  <DownloadSimple size={14} weight="bold" /> Download CSV template
                </a>
              </div>
            </>
          )}

          {error && (
            <div data-testid="import-error" className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm flex items-start gap-2">
              <Warning size={18} weight="fill" className="flex-shrink-0 mt-0.5" /> <span>{error}</span>
            </div>
          )}

          {preview && (
            <div data-testid="import-preview" className="space-y-4">
              <div className="bg-[#10B981]/10 border border-[#10B981]/30 px-4 py-3 text-sm flex items-start gap-2">
                <FileCsv size={18} weight="fill" className="flex-shrink-0 mt-0.5 text-[#10B981]" />
                <div className="text-[#10B981]">
                  Found <span className="font-bold">{preview.parsed.length}</span> player{preview.parsed.length === 1 ? '' : 's'} ready to import
                  {preview.skipped > 0 && <span className="text-[#A3A3A3]"> · {preview.skipped} blank rows skipped</span>}
                </div>
              </div>

              {preview.errors?.length > 0 && (
                <div className="bg-[#FBBF24]/10 border border-[#FBBF24]/30 p-4">
                  <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#FBBF24] mb-2">⚠ {preview.errors.length} warning{preview.errors.length === 1 ? '' : 's'}</p>
                  <ul className="space-y-1 text-xs text-[#FBBF24]/90 max-h-32 overflow-y-auto">
                    {preview.errors.map((e, i) => (
                      <li key={i}>Row {e.row}: {e.reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="border border-white/10 max-h-72 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-[#0A0A0A] sticky top-0">
                    <tr className="text-xs uppercase tracking-wider text-[#A3A3A3]">
                      <th className="px-4 py-2 text-left">#</th>
                      <th className="px-4 py-2 text-left">Name</th>
                      <th className="px-4 py-2 text-left">Pos</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.parsed.map((p, i) => (
                      <tr key={i} className="border-t border-white/5">
                        <td className="px-4 py-2 text-[#A3A3A3] tabular-nums w-12">{p.number ?? '—'}</td>
                        <td className="px-4 py-2 text-white">{p.name}</td>
                        <td className="px-4 py-2 text-[#CFCFCF]">{p.position ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between gap-3">
                <button data-testid="reset-btn" onClick={reset}
                  className="flex items-center gap-2 text-xs font-bold tracking-wider uppercase border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-4 py-3 transition-colors">
                  <ArrowsClockwise size={14} /> Choose different file
                </button>
                <button data-testid="confirm-import-btn" onClick={onConfirm} disabled={importing || preview.parsed.length === 0}
                  className="flex-1 flex items-center justify-center gap-2 bg-[#10B981] hover:bg-[#0EA975] text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors disabled:opacity-50">
                  <CheckCircle size={16} weight="fill" />
                  {importing ? 'Importing...' : `Import ${preview.parsed.length} Player${preview.parsed.length === 1 ? '' : 's'}`}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RosterImportModal;
