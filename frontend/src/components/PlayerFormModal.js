/**
 * PlayerFormModal
 * ----------------
 * Reusable form for creating OR editing a player. Powers both:
 *   - "Add Player" inline form (mode='create', inline=true)
 *   - "Edit Player" modal (mode='edit', inline=false)
 *
 * Fields:
 *   name (required), jersey number, position, birth_year (→ derives age),
 *   current_grade. The grade dropdown covers middle-school through college,
 *   plus a freeform "Other" option for club-team age groups (U10, U12...).
 *
 * Age is computed on-the-fly from birth_year — never stored, so it can't
 * drift stale when the year rolls over.
 */
import { useState, useEffect, useMemo } from 'react';
import { X } from '@phosphor-icons/react';

export const POSITIONS = ['Goalkeeper', 'Defender', 'Midfielder', 'Forward'];

export const GRADE_OPTIONS = [
  '6th', '7th', '8th',
  '9th (Freshman)', '10th (Sophomore)', '11th (Junior)', '12th (Senior)',
  'College Freshman', 'College Sophomore', 'College Junior', 'College Senior',
  'Graduate / Post-Grad',
];

const currentYear = new Date().getFullYear();
const MIN_BIRTH_YEAR = currentYear - 30;  // generous: U30 caps it
const MAX_BIRTH_YEAR = currentYear - 5;   // U5 is the youngest plausible roster age

const emptyForm = {
  name: '',
  number: '',
  position: '',
  birth_year: '',
  current_grade: '',
};

export const ageFromBirthYear = (birthYear) => {
  const y = parseInt(birthYear, 10);
  if (Number.isNaN(y) || y <= 0) return null;
  return currentYear - y;
};

const PlayerFormModal = ({
  mode = 'create', // 'create' | 'edit'
  initial = null,  // player object when mode === 'edit'
  onSubmit,        // async (payload) — payload uses snake_case keys for backend
  onCancel,
  submitting = false,
  inline = false,  // true → render as inline block; false → render as modal overlay
}) => {
  const [form, setForm] = useState(emptyForm);

  // Populate form when entering edit mode
  useEffect(() => {
    if (mode === 'edit' && initial) {
      setForm({
        name: initial.name || '',
        number: initial.number ?? '',
        position: initial.position || '',
        birth_year: initial.birth_year ?? '',
        current_grade: initial.current_grade || '',
      });
    } else {
      setForm(emptyForm);
    }
  }, [mode, initial]);

  const age = useMemo(() => ageFromBirthYear(form.birth_year), [form.birth_year]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    // Build payload — empty strings become null/None so the backend stores nothing
    const payload = {
      name: form.name.trim(),
      number: form.number === '' ? null : parseInt(form.number, 10),
      position: form.position || null,
      birth_year: form.birth_year === '' ? null : parseInt(form.birth_year, 10),
      current_grade: form.current_grade || null,
    };
    await onSubmit(payload);
    // Parent owns close logic; we just reset our own state for next open
    if (mode === 'create') setForm(emptyForm);
  };

  const title = mode === 'edit' ? `Edit Player${initial ? ` — ${initial.name}` : ''}` : 'Register New Player';

  const formBody = (
    <form onSubmit={handleSubmit} data-testid={mode === 'edit' ? 'edit-player-form' : 'add-player-form'}>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        <div className="sm:col-span-2 md:col-span-3">
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Name *</label>
          <input data-testid="player-name-input" type="text" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
        </div>
        <div>
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Jersey Number</label>
          <input data-testid="player-number-input" type="number" inputMode="numeric" min="0" max="99" value={form.number}
            onChange={(e) => setForm({ ...form, number: e.target.value })}
            className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" />
        </div>
        <div>
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Position</label>
          <select data-testid="player-position-select" value={form.position}
            onChange={(e) => setForm({ ...form, position: e.target.value })}
            className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none">
            <option value="">Select...</option>
            {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">
            Birth Year {age !== null && <span className="text-[#10B981] normal-case tracking-normal">· Age {age}</span>}
          </label>
          <input data-testid="player-birth-year-input" type="number" inputMode="numeric"
            min={MIN_BIRTH_YEAR} max={MAX_BIRTH_YEAR} placeholder={`e.g. ${currentYear - 16}`}
            value={form.birth_year}
            onChange={(e) => setForm({ ...form, birth_year: e.target.value })}
            className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" />
        </div>
        <div className="sm:col-span-2">
          <label className="block text-[10px] font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-1">Current Grade</label>
          <select data-testid="player-grade-select" value={form.current_grade}
            onChange={(e) => setForm({ ...form, current_grade: e.target.value })}
            className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none">
            <option value="">Select...</option>
            {GRADE_OPTIONS.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
      </div>
      <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
        <button type="button" data-testid="player-form-cancel-btn" onClick={onCancel}
          className="px-4 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors text-xs font-bold tracking-wider uppercase">
          Cancel
        </button>
        <button data-testid="submit-player-btn" type="submit" disabled={submitting || !form.name.trim()}
          className="bg-[#007AFF] hover:bg-[#005bb5] disabled:opacity-50 disabled:cursor-not-allowed text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors">
          {mode === 'edit' ? 'Save Changes' : 'Add Player'}
        </button>
      </div>
    </form>
  );

  if (inline) {
    return (
      <div className="bg-[#141414] border border-white/10 p-4 sm:p-6 mb-8">
        <h3 className="text-sm font-bold uppercase tracking-wider text-white mb-4">{title}</h3>
        {formBody}
      </div>
    );
  }

  return (
    <div data-testid="player-form-modal-overlay" onClick={onCancel}
      className="fixed inset-0 bg-black/70 z-[100] overflow-y-auto p-4 sm:flex sm:items-center sm:justify-center">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-white/10 max-w-2xl w-full mx-auto my-4 sm:my-0">
        <div className="p-6 border-b border-white/10 flex items-start justify-between">
          <h3 className="text-xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
            {title}
          </h3>
          <button data-testid="close-player-form-modal" onClick={onCancel}
            className="p-1 text-[#666] hover:text-white">
            <X size={20} />
          </button>
        </div>
        <div className="p-6">{formBody}</div>
      </div>
    </div>
  );
};

export default PlayerFormModal;
