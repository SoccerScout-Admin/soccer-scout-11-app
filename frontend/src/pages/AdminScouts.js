import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader } from '../App';
import {
  ArrowLeft, SealCheck, Clock, Buildings, Check, X, GraduationCap, MapPin,
} from '@phosphor-icons/react';

const TABS = [
  { id: 'pending', label: 'Pending', color: '#FBBF24' },
  { id: 'verified', label: 'Verified', color: '#10B981' },
  { id: 'all', label: 'All', color: '#A3A3A3' },
];

const AdminScouts = () => {
  const navigate = useNavigate();
  const [tab, setTab] = useState('pending');
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  const fetchListings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/scout-listings?status=${tab}`, { headers: getAuthHeader() });
      setListings(res.data || []);
    } catch (err) {
      if (err.response?.status === 403) {
        alert('Admin access required.');
        navigate('/');
      }
      setListings([]);
    } finally {
      setLoading(false);
    }
  }, [tab, navigate]);

  useEffect(() => { fetchListings(); }, [fetchListings]);

  const act = async (id, action) => {
    setBusyId(id);
    try {
      await axios.post(`${API}/admin/scout-listings/${id}/${action}`, {}, { headers: getAuthHeader() });
      await fetchListings();
    } catch (err) {
      alert(`Failed to ${action}: ${err.response?.data?.detail || err.message}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-40 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-3">
          <button data-testid="admin-scouts-back-btn" onClick={() => navigate('/admin/users')}
            className="p-2 border border-white/10 hover:bg-[#1F1F1F] transition-colors">
            <ArrowLeft size={20} className="text-white" />
          </button>
          <div>
            <h1 className="text-2xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Scout Listings Admin</h1>
            <p className="text-xs text-[#A3A3A3]">Approve or reject listings before they appear on the public board</p>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <div className="flex items-center gap-2 mb-6 border-b border-white/10">
          {TABS.map(t => (
            <button key={t.id} data-testid={`admin-scouts-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              className={`px-4 py-3 text-xs font-bold tracking-wider uppercase transition-colors ${
                tab === t.id ? 'text-white border-b-2' : 'text-[#A3A3A3] hover:text-white'
              }`}
              style={tab === t.id ? { borderColor: t.color } : {}}>
              {t.label}
            </button>
          ))}
        </div>

        {loading ? (
          <p className="text-center py-10 text-[#A3A3A3]">Loading...</p>
        ) : listings.length === 0 ? (
          <div className="text-center py-20 border border-dashed border-white/10">
            <Buildings size={60} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-lg text-white mb-1">No {tab === 'all' ? '' : tab} listings</p>
            <p className="text-sm text-[#A3A3A3]">
              {tab === 'pending' ? 'All caught up — nothing waiting for review.' : 'Nothing here yet.'}
            </p>
          </div>
        ) : (
          <div className="space-y-4" data-testid="admin-scouts-list">
            {listings.map(l => (
              <div key={l.id} data-testid={`admin-listing-${l.id}`}
                className="bg-[#141414] border border-white/10 p-5">
                <div className="flex flex-col sm:flex-row items-start gap-4">
                  {l.school_logo_url ? (
                    <img src={`${API.replace('/api','')}${l.school_logo_url}`}
                      alt={l.school_name}
                      className="w-14 h-14 object-contain bg-[#0A0A0A] border border-white/10 flex-shrink-0" />
                  ) : (
                    <div className="w-14 h-14 flex items-center justify-center bg-[#0A0A0A] border border-white/10 flex-shrink-0">
                      <Buildings size={24} className="text-[#666]" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <h3 className="text-lg font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>{l.school_name}</h3>
                      {l.verified ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-[#10B981]/15 border border-[#10B981]/40 text-[#10B981] text-[10px] font-bold uppercase tracking-wider">
                          <SealCheck size={10} weight="fill" /> Verified
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-[#FBBF24]/15 border border-[#FBBF24]/40 text-[#FBBF24] text-[10px] font-bold uppercase tracking-wider">
                          <Clock size={10} /> Pending
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[#A3A3A3] mb-1">{l.author_name} · {l.contact_email}</p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#CFCFCF] mb-2">
                      <span className="inline-flex items-center gap-1"><GraduationCap size={12} /> {l.level}</span>
                      <span className="inline-flex items-center gap-1"><MapPin size={12} /> {l.region}</span>
                    </div>
                    <div className="flex flex-wrap gap-1 mb-2">
                      {(l.positions || []).map(p => (
                        <span key={p} className="text-[10px] font-bold uppercase bg-[#007AFF]/15 border border-[#007AFF]/30 text-[#007AFF] px-2 py-0.5">{p}</span>
                      ))}
                    </div>
                    <p className="text-sm text-[#EAEAEA] line-clamp-3">{l.description}</p>
                  </div>
                  <div className="flex flex-col gap-2 flex-shrink-0 w-full sm:w-auto">
                    <button onClick={() => navigate(`/scouts/${l.id}`)}
                      className="text-xs font-bold tracking-wider uppercase border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-3 py-2 transition-colors">
                      View
                    </button>
                    {l.verified ? (
                      <button data-testid={`unverify-btn-${l.id}`} onClick={() => act(l.id, 'unverify')} disabled={busyId === l.id}
                        className="flex items-center justify-center gap-1.5 text-xs font-bold tracking-wider uppercase border border-[#FBBF24]/30 text-[#FBBF24] hover:bg-[#FBBF24]/10 px-3 py-2 transition-colors disabled:opacity-50">
                        <X size={12} weight="bold" /> Unverify
                      </button>
                    ) : (
                      <button data-testid={`verify-btn-${l.id}`} onClick={() => act(l.id, 'verify')} disabled={busyId === l.id}
                        className="flex items-center justify-center gap-1.5 text-xs font-bold tracking-wider uppercase bg-[#10B981] hover:bg-[#0EA975] text-white px-3 py-2 transition-colors disabled:opacity-50">
                        <Check size={12} weight="bold" /> Verify
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};

export default AdminScouts;
