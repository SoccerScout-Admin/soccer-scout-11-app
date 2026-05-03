import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import {
  ArrowLeft, Plus, Eye, Users, CursorClick,
  Buildings, SealCheck, Clock, PencilSimple, GraduationCap, MapPin,
} from '@phosphor-icons/react';

const StatTile = ({ icon: Icon, value, label, color }) => (
  <div className="flex items-center gap-3">
    <div className="w-9 h-9 flex items-center justify-center border" style={{ borderColor: `${color}30`, backgroundColor: `${color}10` }}>
      <Icon size={16} style={{ color }} />
    </div>
    <div>
      <div className="text-xl font-bold leading-none" style={{ color }}>{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-[#888] mt-1">{label}</div>
    </div>
  </div>
);

const ScoutMyListings = () => {
  const navigate = useNavigate();
  const user = getCurrentUser();
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/scout-listings/my`, { headers: getAuthHeader() })
      .then(res => setListings(res.data || []))
      .catch(() => setListings([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-40 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <button data-testid="my-back-btn" onClick={() => navigate('/scouts')}
              className="p-2 border border-white/10 hover:bg-[#1F1F1F] transition-colors flex-shrink-0">
              <ArrowLeft size={20} className="text-white" />
            </button>
            <div className="min-w-0">
              <h1 className="text-2xl sm:text-3xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>My Listings</h1>
              <p className="text-xs text-[#A3A3A3]">Performance insights for {user?.name}</p>
            </div>
          </div>
          <button data-testid="my-new-btn" onClick={() => navigate('/scouts/new')}
            className="flex items-center gap-2 bg-[#10B981] hover:bg-[#0EA975] text-white px-4 py-2 text-xs font-bold tracking-wider uppercase transition-colors flex-shrink-0">
            <Plus size={16} weight="bold" /> New Listing
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <div className="bg-[#141414] border border-[#10B981]/20 p-4 mb-6 text-sm text-[#CFCFCF]">
          📬 Every Monday at 9am UTC, we email you a digest of your listing performance from the past 7 days. Update your settings if you'd rather not receive it.
        </div>

        {loading ? (
          <p className="text-center py-10 text-[#A3A3A3]">Loading...</p>
        ) : listings.length === 0 ? (
          <div className="text-center py-20 border border-dashed border-white/10">
            <Buildings size={60} className="text-[#A3A3A3] mx-auto mb-4" />
            <p className="text-lg text-white mb-1">No listings yet</p>
            <p className="text-sm text-[#A3A3A3] mb-6">Post your first recruiting listing to start collecting interest.</p>
            <button onClick={() => navigate('/scouts/new')}
              className="bg-[#10B981] hover:bg-[#0EA975] text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors">
              + Post Your First Listing
            </button>
          </div>
        ) : (
          <div className="space-y-4" data-testid="my-listings-list">
            {listings.map(l => (
              <div key={l.id} data-testid={`my-listing-${l.id}`}
                className="bg-[#141414] border border-white/10 hover:border-white/20 transition-colors">
                <div className="p-5 flex items-start gap-4">
                  {l.school_logo_url ? (
                    <img src={`${API.replace('/api','')}${l.school_logo_url}`} alt={l.school_name}
                      className="w-14 h-14 object-contain bg-[#0A0A0A] border border-white/10 flex-shrink-0" />
                  ) : (
                    <div className="w-14 h-14 flex items-center justify-center bg-[#0A0A0A] border border-white/10 flex-shrink-0">
                      <Buildings size={24} className="text-[#666]" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <h3 className="text-xl font-bold text-white truncate" style={{ fontFamily: 'Bebas Neue' }}>{l.school_name}</h3>
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
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#A3A3A3]">
                      <span className="inline-flex items-center gap-1"><GraduationCap size={12} /> {l.level}</span>
                      <span className="inline-flex items-center gap-1"><MapPin size={12} /> {l.region}</span>
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 flex-shrink-0">
                    <button onClick={() => navigate(`/scouts/${l.id}`)}
                      className="text-xs font-bold tracking-wider uppercase border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-3 py-2 transition-colors">View</button>
                    <button data-testid={`my-edit-${l.id}`} onClick={() => navigate(`/scouts/edit/${l.id}`)}
                      className="flex items-center justify-center gap-1.5 text-xs font-bold tracking-wider uppercase border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] px-3 py-2 transition-colors">
                      <PencilSimple size={12} /> Edit
                    </button>
                  </div>
                </div>
                {/* Insights */}
                {l.insights && (
                  <div data-testid={`insights-${l.id}`} className="border-t border-white/5 px-5 py-4 grid grid-cols-3 gap-4 bg-[#0F0F0F]">
                    <StatTile icon={Eye} value={l.insights.views_7d} label="Views (7d)" color="#10B981" />
                    <StatTile icon={Users} value={l.insights.unique_coaches_7d} label="Unique coaches" color="#007AFF" />
                    <StatTile icon={CursorClick} value={l.insights.contact_clicks_7d} label="Contact clicks" color="#FBBF24" />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};

export default ScoutMyListings;
