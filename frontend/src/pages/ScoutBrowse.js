import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getCurrentUser } from '../App';
import {
  MagnifyingGlass, Funnel, SealCheck, GraduationCap, MapPin,
  Buildings, Plus, ArrowLeft,
} from '@phosphor-icons/react';

const POSITIONS = ['GK', 'CB', 'FB', 'CM', 'DM', 'AM', 'LW', 'RW', 'ST'];
const LEVELS = ['NCAA D1', 'NCAA D2', 'NCAA D3', 'NAIA', 'JUCO', 'Pro Academy', 'MLS Next', 'ECNL', 'Other'];

const ScoutBrowse = () => {
  const navigate = useNavigate();
  const user = getCurrentUser();
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedPositions, setSelectedPositions] = useState([]);
  const [selectedLevel, setSelectedLevel] = useState('');
  const [selectedYear, setSelectedYear] = useState('');
  const [region, setRegion] = useState('');
  const [q, setQ] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  const currentYear = new Date().getFullYear();
  const years = useMemo(() => Array.from({ length: 6 }, (_, i) => currentYear + i), [currentYear]);

  const fetchListings = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedPositions.length) params.set('positions', selectedPositions.join(','));
      if (selectedLevel) params.set('level', selectedLevel);
      if (selectedYear) params.set('grad_years', String(selectedYear));
      if (region.trim()) params.set('region', region.trim());
      if (q.trim()) params.set('q', q.trim());
      const res = await axios.get(`${API}/scout-listings?${params.toString()}`);
      setListings(res.data || []);
    } catch {
      setListings([]);
    } finally {
      setLoading(false);
    }
  }, [selectedPositions, selectedLevel, selectedYear, region, q]);

  useEffect(() => { fetchListings(); }, [fetchListings]);

  const togglePosition = (p) => {
    setSelectedPositions(prev => prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]);
  };

  const isScout = user && (user.role === 'scout' || user.role === 'college_coach' || user.role === 'admin' || user.role === 'owner');

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-40 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <button data-testid="scout-back-btn" onClick={() => navigate(user ? '/' : '/auth')}
              className="p-2 border border-white/10 hover:bg-[#1F1F1F] transition-colors flex-shrink-0">
              <ArrowLeft size={20} className="text-white" />
            </button>
            <div className="min-w-0">
              <h1 className="text-2xl sm:text-3xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>Scout Board</h1>
              <p className="text-xs text-[#A3A3A3] truncate">Recruiting needs from scouts and college coaches</p>
            </div>
          </div>
          {isScout && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <button data-testid="my-listings-btn" onClick={() => navigate('/scouts/my')}
                className="text-xs font-bold tracking-wider uppercase border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-3 py-2 transition-colors hidden sm:inline-block">
                My Listings
              </button>
              <button data-testid="new-listing-btn" onClick={() => navigate('/scouts/new')}
                className="flex items-center gap-2 bg-[#10B981] hover:bg-[#0EA975] text-white px-4 py-2 text-xs font-bold tracking-wider uppercase transition-colors">
                <Plus size={16} weight="bold" /> Post Listing
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        {/* Search + filter toggle */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mb-6">
          <div className="flex-1 relative">
            <MagnifyingGlass size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
            <input data-testid="scout-search-input" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Search by school name or keyword..."
              className="w-full bg-[#141414] border border-white/10 text-white pl-10 pr-4 py-3 focus:border-[#10B981] focus:outline-none text-sm" />
          </div>
          <button data-testid="toggle-filters-btn" onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-2 px-4 py-3 text-xs font-bold tracking-wider uppercase border transition-colors flex-shrink-0 ${
              showFilters ? 'border-[#10B981] text-[#10B981] bg-[#10B981]/10' : 'border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F]'
            }`}>
            <Funnel size={14} weight="bold" /> Filters
          </button>
        </div>

        {showFilters && (
          <div data-testid="filters-panel" className="bg-[#141414] border border-white/10 p-4 sm:p-6 mb-6 space-y-5">
            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Positions</label>
              <div className="flex flex-wrap gap-2">
                {POSITIONS.map(p => (
                  <button key={p} data-testid={`filter-pos-${p}`}
                    onClick={() => togglePosition(p)}
                    className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wider border transition-colors ${
                      selectedPositions.includes(p)
                        ? 'bg-[#10B981] border-[#10B981] text-white'
                        : 'border-white/10 text-[#A3A3A3] hover:text-white hover:border-white/30'
                    }`}>{p}</button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Level</label>
                <select data-testid="filter-level" value={selectedLevel} onChange={(e) => setSelectedLevel(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm">
                  <option value="">All levels</option>
                  {LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Grad Year</label>
                <select data-testid="filter-year" value={selectedYear} onChange={(e) => setSelectedYear(e.target.value)}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm">
                  <option value="">Any year</option>
                  {years.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Region</label>
                <input data-testid="filter-region" value={region} onChange={(e) => setRegion(e.target.value)}
                  placeholder="e.g. Midwest"
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-3 py-2 focus:border-[#10B981] focus:outline-none text-sm" />
              </div>
            </div>

            {(selectedPositions.length > 0 || selectedLevel || selectedYear || region || q) && (
              <button data-testid="clear-filters-btn"
                onClick={() => { setSelectedPositions([]); setSelectedLevel(''); setSelectedYear(''); setRegion(''); setQ(''); }}
                className="text-xs text-[#A3A3A3] hover:text-white underline">
                Clear all filters
              </button>
            )}
          </div>
        )}

        {/* Feed */}
        {loading ? (
          <div className="text-center py-20 text-[#A3A3A3]">Loading listings...</div>
        ) : listings.length === 0 ? (
          <div data-testid="scout-empty-state" className="text-center py-20 border border-dashed border-white/10">
            <Buildings size={60} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-lg text-white mb-1">No listings yet</p>
            <p className="text-sm text-[#A3A3A3]">
              {q || selectedPositions.length || selectedLevel || selectedYear || region
                ? 'No listings match your filters — try clearing them.'
                : 'Be the first to post a recruiting listing.'}
            </p>
          </div>
        ) : (
          <div className="space-y-4" data-testid="scout-listings-feed">
            {listings.map(l => (
              <button key={l.id} data-testid={`listing-card-${l.id}`}
                onClick={() => navigate(`/scouts/${l.id}`)}
                className="w-full text-left bg-[#141414] border border-white/10 hover:border-[#10B981]/40 hover:bg-[#1a1a1a] transition-all p-5 sm:p-6 group">
                <div className="flex items-start gap-4">
                  {l.school_logo_url ? (
                    <img src={`${API.replace('/api','')}${l.school_logo_url}`}
                      alt={l.school_name}
                      className="w-14 h-14 sm:w-16 sm:h-16 object-contain bg-[#0A0A0A] border border-white/10 flex-shrink-0" />
                  ) : (
                    <div className="w-14 h-14 sm:w-16 sm:h-16 flex items-center justify-center bg-[#0A0A0A] border border-white/10 flex-shrink-0">
                      <Buildings size={28} className="text-[#666]" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <h3 className="text-xl sm:text-2xl font-bold text-white truncate" style={{ fontFamily: 'Bebas Neue' }}>
                        {l.school_name}
                      </h3>
                      {l.verified && (
                        <span data-testid={`verified-badge-${l.id}`}
                          className="inline-flex items-center gap-1 px-2 py-0.5 bg-[#10B981]/15 border border-[#10B981]/40 text-[#10B981] text-[10px] font-bold uppercase tracking-wider">
                          <SealCheck size={12} weight="fill" /> Verified
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#A3A3A3] mb-3">
                      <span className="inline-flex items-center gap-1"><GraduationCap size={14} /> {l.level}</span>
                      <span className="inline-flex items-center gap-1"><MapPin size={14} /> {l.region}</span>
                      {l.grad_years?.length > 0 && <span>Class of {l.grad_years.join(', ')}</span>}
                    </div>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {(l.positions || []).map(p => (
                        <span key={p} className="text-[10px] font-bold uppercase tracking-wider bg-[#007AFF]/15 border border-[#007AFF]/30 text-[#007AFF] px-2 py-0.5">{p}</span>
                      ))}
                    </div>
                    <p className="text-sm text-[#CFCFCF] line-clamp-2">{l.description}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Nudge anonymous viewers */}
        {!user && listings.length > 0 && (
          <div className="mt-8 p-5 bg-[#0a1a2e] border border-[#007AFF]/30 text-sm text-[#CFCFCF] text-center">
            <p className="mb-2">Contact info and school websites are visible to registered coaches only.</p>
            <button onClick={() => navigate('/auth')}
              data-testid="login-cta"
              className="text-[#007AFF] font-bold hover:underline">Log in or sign up →</button>
          </div>
        )}
      </main>
    </div>
  );
};

export default ScoutBrowse;
