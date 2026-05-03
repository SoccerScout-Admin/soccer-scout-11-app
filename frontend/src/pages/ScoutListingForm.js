import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import { ArrowLeft, UploadSimple, Buildings } from '@phosphor-icons/react';

const POSITIONS = ['GK', 'CB', 'FB', 'CM', 'DM', 'AM', 'LW', 'RW', 'ST'];
const LEVELS = ['NCAA D1', 'NCAA D2', 'NCAA D3', 'NAIA', 'JUCO', 'Pro Academy', 'MLS Next', 'ECNL', 'Other'];

const empty = {
  school_name: '',
  website_url: '',
  positions: [],
  grad_years: [],
  level: 'NCAA D1',
  region: '',
  gpa_requirement: '',
  recruiting_timeline: '',
  contact_email: '',
  description: '',
};

const ScoutListingForm = () => {
  const { listingId } = useParams();
  const isEdit = Boolean(listingId);
  const navigate = useNavigate();
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [existingLogoUrl, setExistingLogoUrl] = useState(null);
  const [logoFile, setLogoFile] = useState(null);

  const currentYear = new Date().getFullYear();
  const years = useMemo(() => Array.from({ length: 6 }, (_, i) => currentYear + i), [currentYear]);

  useEffect(() => {
    if (!isEdit) return;
    axios.get(`${API}/scout-listings/${listingId}`, { headers: getAuthHeader() })
      .then(res => {
        const d = res.data;
        setForm({
          school_name: d.school_name || '',
          website_url: d.website_url || '',
          positions: d.positions || [],
          grad_years: d.grad_years || [],
          level: d.level || 'NCAA D1',
          region: d.region || '',
          gpa_requirement: d.gpa_requirement || '',
          recruiting_timeline: d.recruiting_timeline || '',
          contact_email: d.contact_email || '',
          description: d.description || '',
        });
        setExistingLogoUrl(d.school_logo_url || null);
      })
      .catch(() => setError('Could not load listing.'));
  }, [isEdit, listingId]);

  const toggle = (field, val) => {
    setForm(prev => ({
      ...prev,
      [field]: prev[field].includes(val)
        ? prev[field].filter(x => x !== val)
        : [...prev[field], val],
    }));
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');

    // Client-side validation mirror of the backend
    if (form.school_name.trim().length < 2) return setError('School name is required.');
    if (!form.region.trim()) return setError('Region is required.');
    if (form.description.trim().length < 10) return setError('Description must be at least 10 characters.');
    if (!form.positions.length) return setError('Pick at least one position.');
    if (!form.grad_years.length) return setError('Pick at least one graduation year.');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.contact_email)) return setError('Enter a valid contact email.');

    const payload = {
      school_name: form.school_name.trim(),
      positions: form.positions,
      grad_years: form.grad_years.map(Number),
      level: form.level,
      region: form.region.trim(),
      contact_email: form.contact_email.trim().toLowerCase(),
      description: form.description.trim(),
    };
    if (form.website_url.trim()) payload.website_url = form.website_url.trim();
    if (form.gpa_requirement.trim()) payload.gpa_requirement = form.gpa_requirement.trim();
    if (form.recruiting_timeline.trim()) payload.recruiting_timeline = form.recruiting_timeline.trim();

    setSaving(true);
    try {
      let savedId = listingId;
      if (isEdit) {
        await axios.patch(`${API}/scout-listings/${listingId}`, payload, { headers: getAuthHeader() });
      } else {
        const res = await axios.post(`${API}/scout-listings`, payload, { headers: getAuthHeader() });
        savedId = res.data.id;
      }
      if (logoFile && savedId) {
        const fd = new FormData();
        fd.append('file', logoFile);
        await axios.post(`${API}/scout-listings/${savedId}/logo`, fd, {
          headers: { ...getAuthHeader(), 'Content-Type': 'multipart/form-data' },
        });
      }
      navigate(`/scouts/${savedId}`);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Save failed. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-40 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <button data-testid="form-back-btn" onClick={() => navigate('/scouts')}
            className="p-2 border border-white/10 hover:bg-[#1F1F1F] transition-colors">
            <ArrowLeft size={20} className="text-white" />
          </button>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>
            {isEdit ? 'Edit Listing' : 'New Recruiting Listing'}
          </h1>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        <form onSubmit={onSubmit} data-testid="listing-form" className="space-y-6">
          {/* Logo */}
          <div className="bg-[#141414] border border-white/10 p-5">
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">School Logo</label>
            <div className="flex items-center gap-4">
              <div className="w-20 h-20 bg-[#0A0A0A] border border-white/10 flex items-center justify-center flex-shrink-0 overflow-hidden">
                {logoFile ? (
                  <img src={URL.createObjectURL(logoFile)} alt="preview" className="w-full h-full object-contain" />
                ) : existingLogoUrl ? (
                  <img src={`${API.replace('/api','')}${existingLogoUrl}`} alt="current" className="w-full h-full object-contain" />
                ) : (
                  <Buildings size={28} className="text-[#666]" />
                )}
              </div>
              <label className="cursor-pointer">
                <input data-testid="logo-file-input" type="file" accept="image/*"
                  onChange={(e) => setLogoFile(e.target.files?.[0] || null)} className="hidden" />
                <span className="inline-flex items-center gap-2 text-xs font-bold tracking-wider uppercase border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-4 py-2 transition-colors">
                  <UploadSimple size={14} /> {logoFile ? logoFile.name : 'Choose Image'}
                </span>
              </label>
            </div>
          </div>

          {/* Core identity */}
          <div className="bg-[#141414] border border-white/10 p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">School / Club Name *</label>
              <input data-testid="school-name-input" value={form.school_name}
                onChange={(e) => setForm({ ...form, school_name: e.target.value })}
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" required />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Website URL</label>
              <input data-testid="website-url-input" type="url" value={form.website_url}
                onChange={(e) => setForm({ ...form, website_url: e.target.value })}
                placeholder="https://..."
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Level *</label>
              <select data-testid="level-select" value={form.level}
                onChange={(e) => setForm({ ...form, level: e.target.value })}
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm">
                {LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Region *</label>
              <input data-testid="region-input" value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="e.g. Midwest, Chicago metro"
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" required />
            </div>
          </div>

          {/* Positions */}
          <div className="bg-[#141414] border border-white/10 p-5">
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">Positions Needed *</label>
            <div className="flex flex-wrap gap-2">
              {POSITIONS.map(p => (
                <button key={p} type="button" data-testid={`form-pos-${p}`}
                  onClick={() => toggle('positions', p)}
                  className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border transition-colors ${
                    form.positions.includes(p)
                      ? 'bg-[#10B981] border-[#10B981] text-white'
                      : 'border-white/10 text-[#A3A3A3] hover:text-white hover:border-white/30'
                  }`}>{p}</button>
              ))}
            </div>
          </div>

          {/* Grad years */}
          <div className="bg-[#141414] border border-white/10 p-5">
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">Graduation Classes *</label>
            <div className="flex flex-wrap gap-2">
              {years.map(y => (
                <button key={y} type="button" data-testid={`form-year-${y}`}
                  onClick={() => toggle('grad_years', y)}
                  className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border transition-colors ${
                    form.grad_years.includes(y)
                      ? 'bg-[#A855F7] border-[#A855F7] text-white'
                      : 'border-white/10 text-[#A3A3A3] hover:text-white hover:border-white/30'
                  }`}>{y}</button>
              ))}
            </div>
          </div>

          {/* Requirements + timeline */}
          <div className="bg-[#141414] border border-white/10 p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Academic Requirements</label>
              <input data-testid="gpa-input" value={form.gpa_requirement}
                onChange={(e) => setForm({ ...form, gpa_requirement: e.target.value })}
                placeholder="e.g. 3.3 min GPA, 1200 SAT"
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Recruiting Timeline</label>
              <input data-testid="timeline-input" value={form.recruiting_timeline}
                onChange={(e) => setForm({ ...form, recruiting_timeline: e.target.value })}
                placeholder="e.g. Evaluating through summer 2026"
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" />
            </div>
          </div>

          {/* Contact + description */}
          <div className="bg-[#141414] border border-white/10 p-5 space-y-4">
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Contact Email *</label>
              <input data-testid="contact-email-input" type="email" value={form.contact_email}
                onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                placeholder="coach@school.edu"
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" required />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Coach's Notes *</label>
              <textarea data-testid="description-input" value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={6}
                placeholder="Describe the profile you're looking for — playing style, technical traits, character, etc."
                className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm resize-y" required />
              <p className="text-[11px] text-[#666] mt-1">{form.description.length} / 2000</p>
            </div>
          </div>

          {error && (
            <div data-testid="form-error" className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm">{error}</div>
          )}

          <div className="bg-[#141414] border border-[#FBBF24]/30 p-4 text-sm text-[#FBBF24]">
            <p className="font-bold text-xs tracking-wider uppercase mb-1">Admin review</p>
            <p className="text-[#EFB100]/90 text-[13px]">Every listing (new or edited) is reviewed by an admin before it appears on the public board. You'll see a "Pending Verification" badge until approved.</p>
          </div>

          <div className="flex items-center gap-3">
            <button type="button" onClick={() => navigate('/scouts')}
              className="border border-white/10 text-white py-3 px-6 font-bold tracking-wider uppercase text-xs hover:bg-[#1F1F1F] transition-colors">
              Cancel
            </button>
            <button data-testid="submit-listing-btn" type="submit" disabled={saving}
              className="flex-1 bg-[#10B981] hover:bg-[#0EA975] text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors disabled:opacity-50">
              {saving ? 'Saving...' : (isEdit ? 'Save Changes' : 'Post Listing')}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
};

export default ScoutListingForm;
