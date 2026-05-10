import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { formatTime } from './utils/time';

/**
 * Inline form for adding annotations (note / tactical / key_moment).
 * Now includes a "Templates" chip row — coaches can one-click insert their
 * most-used phrases (sorted by usage_count) and pin the current text as a new template.
 */
const AnnotationForm = ({
  annotationMode,
  currentTimestamp,
  annotationText,
  setAnnotationText,
  selectedPlayerId,
  setSelectedPlayerId,
  players,
  onClose,
  onSave,
}) => {
  const [templates, setTemplates] = useState([]);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [templateError, setTemplateError] = useState(null);

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/annotation-templates`, {
        params: { annotation_type: annotationMode },
        headers: getAuthHeader(),
      });
      setTemplates(res.data || []);
    } catch (err) {
      console.error('Failed to load templates:', err);
    }
  }, [annotationMode]);

  useEffect(() => {
    if (annotationMode) fetchTemplates();
  }, [annotationMode, fetchTemplates]);

  const applyTemplate = async (t) => {
    setAnnotationText(t.text);
    // Fire-and-forget usage increment so it floats to the top next time
    try {
      await axios.post(`${API}/annotation-templates/${t.id}/use`, {}, { headers: getAuthHeader() });
      setTemplates((prev) =>
        [...prev]
          .map((p) => (p.id === t.id ? { ...p, usage_count: (p.usage_count || 0) + 1 } : p))
          .sort((a, b) => (b.usage_count || 0) - (a.usage_count || 0))
      );
    } catch (err) {
      console.error('Failed to increment template usage:', err);
    }
  };

  const saveAsTemplate = async () => {
    const text = annotationText.trim();
    if (!text) return;
    setSavingTemplate(true);
    setTemplateError(null);
    try {
      const res = await axios.post(
        `${API}/annotation-templates`,
        { text, annotation_type: annotationMode },
        { headers: getAuthHeader() }
      );
      if (res.data?.duplicate) {
        setTemplateError('Already saved');
      } else {
        await fetchTemplates();
      }
    } catch (err) {
      setTemplateError(err.response?.data?.detail || 'Failed to save');
    } finally {
      setSavingTemplate(false);
      setTimeout(() => setTemplateError(null), 2500);
    }
  };

  // Hide save-as-template if the current text exactly matches an existing template
  const textMatchesExisting = templates.some((t) => t.text === annotationText.trim());
  const visibleTemplates = templates.slice(0, 6);

  return (
    <div className="bg-[#111] rounded-lg border border-white/10 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ fontFamily: 'Space Grotesk' }}>
          Add {annotationMode?.replace('_', ' ')} at {formatTime(currentTimestamp)}
        </h3>
        <button data-testid="close-annotation-form-btn" onClick={onClose}
          className="text-[#666] hover:text-white">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
      </div>

      {/* Templates chip row */}
      {visibleTemplates.length > 0 && (
        <div data-testid="annotation-templates-row" className="mb-3">
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[10px] text-[#666] uppercase tracking-wider">Quick Templates</label>
            <span className="text-[9px] text-[#444]">{templates.length} saved</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {visibleTemplates.map((t) => (
              <button key={t.id} type="button"
                data-testid={`annotation-template-${t.id}`}
                onClick={() => applyTemplate(t)}
                title={t.usage_count > 0 ? `Used ${t.usage_count}×` : undefined}
                className="text-[10px] text-[#A3A3A3] bg-white/5 hover:bg-[#007AFF]/15 hover:text-[#007AFF] border border-white/10 hover:border-[#007AFF]/30 px-2 py-1 transition-colors max-w-[220px] truncate">
                {t.text}
              </button>
            ))}
          </div>
        </div>
      )}

      <textarea data-testid="annotation-text-input" value={annotationText}
        onChange={(e) => setAnnotationText(e.target.value)}
        className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 mb-3 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none resize-none" rows="3"
        placeholder="Enter your annotation..." />

      {players.length > 0 && (
        <div className="mb-3">
          <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Tag Player (optional)</label>
          <select data-testid="annotation-player-select" value={selectedPlayerId}
            onChange={(e) => setSelectedPlayerId(e.target.value)}
            className="w-full bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none">
            <option value="">No player</option>
            {players.map((p) => (
              <option key={p.id} value={p.id}>#{p.number ?? '?'} {p.name} ({p.team})</option>
            ))}
          </select>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button data-testid="save-annotation-btn" onClick={onSave}
          className="bg-[#007AFF] hover:bg-[#0066DD] text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          Save Annotation
        </button>
        {annotationText.trim() && !textMatchesExisting && (
          <button data-testid="save-as-template-btn" onClick={saveAsTemplate} disabled={savingTemplate}
            title="Save current text as a reusable template"
            className="flex items-center gap-1.5 text-xs text-[#A855F7] hover:text-[#C084FC] border border-[#A855F7]/30 hover:bg-[#A855F7]/10 px-3 py-2 rounded-lg transition-colors disabled:opacity-50">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V6h1V2H8v4h1v4.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V17z"/></svg>
            {savingTemplate ? 'Saving...' : 'Save as template'}
          </button>
        )}
        {templateError && (
          <span data-testid="template-error" className="text-[10px] text-[#FBBF24]">{templateError}</span>
        )}
      </div>
    </div>
  );
};

export default AnnotationForm;
