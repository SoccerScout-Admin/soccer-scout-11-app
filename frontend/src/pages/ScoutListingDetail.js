import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import {
  ArrowLeft, SealCheck, GraduationCap, MapPin, Globe,
  Envelope, Buildings, PencilSimple, Trash, Clock, Star, Eye,
  PaperPlaneRight,
} from '@phosphor-icons/react';
import ExpressInterestModal from './components/ExpressInterestModal';

const ScoutListingDetail = () => {
  const { listingId } = useParams();
  const navigate = useNavigate();
  const user = getCurrentUser();
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [ownerInsights, setOwnerInsights] = useState(null);
  const [showInterestModal, setShowInterestModal] = useState(false);

  const fetchListing = useCallback(async () => {
    setLoading(true);
    try {
      const headers = user ? getAuthHeader() : {};
      const res = await axios.get(`${API}/scout-listings/${listingId}`, { headers });
      setListing(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Listing not found.');
    } finally {
      setLoading(false);
    }
  }, [listingId, user]);

  useEffect(() => { fetchListing(); }, [fetchListing]);

  // Fetch owner-only insights once we know we're viewing our own listing.
  useEffect(() => {
    if (!user || !listing || listing.user_id !== user.id) return;
    axios.get(`${API}/scout-listings/${listingId}/insights`, { headers: getAuthHeader() })
      .then(res => setOwnerInsights(res.data))
      .catch(() => setOwnerInsights(null));
  }, [user, listing, listingId]);

  const handleDelete = async () => {
    if (!window.confirm('Delete this listing? This cannot be undone.')) return;
    try {
      await axios.delete(`${API}/scout-listings/${listingId}`, { headers: getAuthHeader() });
      navigate('/scouts');
    } catch (err) {
      alert('Failed to delete: ' + (err.response?.data?.detail || err.message));
    }
  };

  if (loading) {
    return <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center text-[#A3A3A3]">Loading...</div>;
  }
  if (error || !listing) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center p-6">
        <div className="max-w-md text-center">
          <Buildings size={60} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Listing not available</h1>
          <p className="text-sm text-[#A3A3A3] mb-6">{error}</p>
          <button onClick={() => navigate('/scouts')}
            className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors">
            Back to Scout Board
          </button>
        </div>
      </div>
    );
  }

  const isOwner = user && user.id === listing.user_id;
  const contactGated = listing._contact_gated;

  return (
    <div className="min-h-screen bg-[#0A0A0A]">
      <header className="sticky top-0 z-40 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <button data-testid="detail-back-btn" onClick={() => navigate('/scouts')}
              className="p-2 border border-white/10 hover:bg-[#1F1F1F] transition-colors">
              <ArrowLeft size={20} className="text-white" />
            </button>
            <h1 className="text-xl font-bold truncate" style={{ fontFamily: 'Bebas Neue' }}>Listing Detail</h1>
          </div>
          {isOwner && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <button data-testid="edit-listing-btn" onClick={() => navigate(`/scouts/edit/${listing.id}`)}
                className="p-2 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] transition-colors">
                <PencilSimple size={16} />
              </button>
              <button data-testid="delete-listing-btn" onClick={handleDelete}
                className="p-2 border border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10 transition-colors">
                <Trash size={16} />
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        {/* Hero */}
        <div className="bg-[#141414] border border-white/10 p-5 sm:p-8 mb-6">
          <div className="flex items-start gap-5">
            {listing.school_logo_url ? (
              <img src={`${API.replace('/api','')}${listing.school_logo_url}`}
                alt={listing.school_name}
                className="w-20 h-20 sm:w-24 sm:h-24 object-contain bg-[#0A0A0A] border border-white/10 flex-shrink-0" />
            ) : (
              <div className="w-20 h-20 sm:w-24 sm:h-24 flex items-center justify-center bg-[#0A0A0A] border border-white/10 flex-shrink-0">
                <Buildings size={40} className="text-[#666]" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <h2 className="text-3xl sm:text-4xl font-bold text-white" style={{ fontFamily: 'Bebas Neue' }}>
                  {listing.school_name}
                </h2>
                {listing.verified ? (
                  <span className="inline-flex items-center gap-1 px-2 py-1 bg-[#10B981]/15 border border-[#10B981]/40 text-[#10B981] text-[10px] font-bold uppercase tracking-wider">
                    <SealCheck size={12} weight="fill" /> Verified
                  </span>
                ) : (
                  <span data-testid="pending-badge" className="inline-flex items-center gap-1 px-2 py-1 bg-[#FBBF24]/15 border border-[#FBBF24]/40 text-[#FBBF24] text-[10px] font-bold uppercase tracking-wider">
                    <Clock size={12} /> Pending Verification
                  </span>
                )}
              </div>
              <p className="text-sm text-[#A3A3A3] mb-1">Posted by {listing.author_name}</p>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[#CFCFCF]">
                <span className="inline-flex items-center gap-1.5"><GraduationCap size={16} /> {listing.level}</span>
                <span className="inline-flex items-center gap-1.5"><MapPin size={16} /> {listing.region}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Positions + grad years */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          <div className="bg-[#141414] border border-white/10 p-5">
            <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">Positions Needed</p>
            <div className="flex flex-wrap gap-2">
              {(listing.positions || []).map(p => (
                <span key={p} className="text-sm font-bold uppercase tracking-wider bg-[#007AFF]/15 border border-[#007AFF]/30 text-[#007AFF] px-3 py-1.5">{p}</span>
              ))}
              {!listing.positions?.length && <span className="text-sm text-[#666]">Not specified</span>}
            </div>
          </div>
          <div className="bg-[#141414] border border-white/10 p-5">
            <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">Graduation Classes</p>
            <div className="flex flex-wrap gap-2">
              {(listing.grad_years || []).map(y => (
                <span key={y} className="text-sm font-bold uppercase tracking-wider bg-[#A855F7]/15 border border-[#A855F7]/30 text-[#A855F7] px-3 py-1.5">Class of {y}</span>
              ))}
              {!listing.grad_years?.length && <span className="text-sm text-[#666]">Not specified</span>}
            </div>
          </div>
        </div>

        {/* Description */}
        <div className="bg-[#141414] border border-white/10 p-5 sm:p-6 mb-6">
          <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">Coach's Notes</p>
          <p className="text-[15px] text-[#EAEAEA] leading-relaxed whitespace-pre-wrap">{listing.description}</p>
        </div>

        {/* Requirements + timeline */}
        {(listing.gpa_requirement || listing.recruiting_timeline) && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            {listing.gpa_requirement && (
              <div className="bg-[#141414] border border-white/10 p-5">
                <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2 flex items-center gap-2"><Star size={14} /> Academic Requirements</p>
                <p className="text-sm text-[#EAEAEA]">{listing.gpa_requirement}</p>
              </div>
            )}
            {listing.recruiting_timeline && (
              <div className="bg-[#141414] border border-white/10 p-5">
                <p className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2 flex items-center gap-2"><Clock size={14} /> Timeline</p>
                <p className="text-sm text-[#EAEAEA]">{listing.recruiting_timeline}</p>
              </div>
            )}
          </div>
        )}

        {/* Contact block (gated) */}
        <div className="bg-gradient-to-r from-[#0a1a2e] to-[#141414] border border-[#007AFF]/30 p-5 sm:p-6">
          <p className="text-xs font-bold tracking-[0.3em] uppercase text-[#007AFF] mb-3">Get in Touch</p>
          {contactGated ? (
            <div data-testid="contact-gated">
              <p className="text-sm text-[#CFCFCF] mb-4">Contact details and the school website are visible to registered coaches only.</p>
              <button data-testid="login-to-see-contact-btn" onClick={() => navigate('/auth')}
                className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-6 py-3 font-bold tracking-wider uppercase text-xs transition-colors">
                Log in or Sign up →
              </button>
            </div>
          ) : (
            <div data-testid="contact-visible" className="space-y-3">
              {!isOwner && (
                <button data-testid="express-interest-btn"
                  onClick={() => setShowInterestModal(true)}
                  className="w-full flex items-center justify-center gap-2 bg-[#10B981] hover:bg-[#0EA975] text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors mb-2">
                  <PaperPlaneRight size={16} weight="fill" /> Express Interest
                </button>
              )}
              {listing.website_url && (
                <a href={listing.website_url} target="_blank" rel="noopener noreferrer"
                  onClick={() => { axios.post(`${API}/scout-listings/${listingId}/contact-click`, {}, { headers: getAuthHeader() }).catch(() => {}); }}
                  className="flex items-center gap-3 text-[#007AFF] hover:text-white transition-colors">
                  <Globe size={20} />
                  <span className="text-sm font-medium break-all">{listing.website_url}</span>
                </a>
              )}
              {listing.contact_email && (
                <a href={`mailto:${listing.contact_email}?subject=Interest%20in%20${encodeURIComponent(listing.school_name)}`}
                  onClick={() => { axios.post(`${API}/scout-listings/${listingId}/contact-click`, {}, { headers: getAuthHeader() }).catch(() => {}); }}
                  className="flex items-center gap-3 text-[#10B981] hover:text-white transition-colors">
                  <Envelope size={20} />
                  <span className="text-sm font-medium">{listing.contact_email}</span>
                </a>
              )}
            </div>
          )}
        </div>
      </main>

      {/* Floating insights chip — owner-only */}
      {ownerInsights && (
        <div data-testid="floating-insights-chip"
          className="fixed bottom-5 right-5 z-30 bg-[#10B981] text-white px-4 py-3 shadow-lg border border-[#0EA975] flex items-center gap-2 hover:bg-[#0EA975] cursor-pointer"
          onClick={() => navigate('/scouts/my')}
          title="See full insights">
          <Eye size={20} weight="fill" />
          <div className="text-xs">
            <div className="text-[10px] uppercase tracking-wider opacity-80">past 7d</div>
            <div className="text-base font-bold leading-tight">
              {ownerInsights.views_7d} {ownerInsights.views_7d === 1 ? 'view' : 'views'}
              {ownerInsights.contact_clicks_7d > 0 && ` · ${ownerInsights.contact_clicks_7d} click${ownerInsights.contact_clicks_7d === 1 ? '' : 's'}`}
            </div>
          </div>
        </div>
      )}

      {showInterestModal && (
        <ExpressInterestModal
          listingId={listingId}
          schoolName={listing.school_name}
          onClose={() => setShowInterestModal(false)}
          onSent={(data) => {
            navigate(`/messages/${data.thread_id}`);
          }}
        />
      )}
    </div>
  );
};

export default ScoutListingDetail;
