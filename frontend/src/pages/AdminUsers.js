import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import { ArrowLeft, Shield, MagnifyingGlass, ShieldCheck, UserMinus, Warning, Crown, EnvelopeSimple, X } from '@phosphor-icons/react';
import EmailQueueCard from './components/EmailQueueCard';
import GameOfTheWeekAdmin from './components/GameOfTheWeekAdmin';

const ROLE_META = {
  owner: { label: 'OWNER', color: '#F472B6', icon: Crown },
  admin: { label: 'ADMIN', color: '#A855F7', icon: ShieldCheck },
  analyst: { label: 'ANALYST', color: '#10B981', icon: Shield },
  coach: { label: 'COACH', color: '#60A5FA', icon: Shield },
};

const AdminUsers = () => {
  const navigate = useNavigate();
  const me = getCurrentUser();
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [previewUser, setPreviewUser] = useState(null);
  const [previewHtml, setPreviewHtml] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);

  const fetchUsers = useCallback(async (q = '') => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/users`, {
        headers: getAuthHeader(),
        params: q ? { q } : {},
      });
      setUsers(res.data);
      setError(null);
    } catch (err) {
      setError(err.response?.status === 403
        ? 'Admin access required. Ask an admin to promote you.'
        : err.response?.data?.detail || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const onSearchSubmit = (e) => {
    e.preventDefault();
    fetchUsers(query.trim());
  };

  const setRole = async (userId, newRole) => {
    if (!window.confirm(`Change role to "${newRole}"?`)) return;
    setBusyId(userId);
    try {
      await axios.post(`${API}/admin/users/${userId}/role`, { role: newRole }, { headers: getAuthHeader() });
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u)));
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to update role');
    } finally {
      setBusyId(null);
    }
  };

  const openPreview = async (u) => {
    setPreviewUser(u);
    setPreviewHtml('');
    setLoadingPreview(true);
    try {
      const res = await axios.get(`${API}/coach-pulse/admin-preview/${u.id}`, {
        headers: getAuthHeader(),
        responseType: 'text',
      });
      setPreviewHtml(res.data);
    } catch (err) {
      setPreviewHtml(`<p style="color:#EF4444;font-family:sans-serif;padding:20px;">Failed to load preview: ${err.response?.data?.detail || err.message}</p>`);
    } finally {
      setLoadingPreview(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button data-testid="admin-back-btn" onClick={() => navigate('/')}
              className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-2">
              <ShieldCheck size={22} weight="bold" className="text-[#A855F7]" />
              <h1 className="text-2xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
                Admin — Users
              </h1>
            </div>
          </div>
          <span className="text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3] bg-white/5 px-3 py-1.5">
            {users.length} user{users.length !== 1 ? 's' : ''}
          </span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <GameOfTheWeekAdmin />
        <EmailQueueCard />

        {/* Search */}
        <form onSubmit={onSearchSubmit} className="flex gap-2 mb-6">
          <div className="relative flex-1">
            <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#666]" />
            <input data-testid="user-search-input" value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by email or name"
              className="w-full bg-[#141414] border border-white/10 text-white px-10 py-3 text-sm focus:border-[#007AFF] focus:outline-none" />
          </div>
          <button data-testid="search-btn" type="submit"
            className="px-5 py-3 bg-[#007AFF] hover:bg-[#005bb5] text-white text-xs font-bold tracking-wider uppercase transition-colors">
            Search
          </button>
        </form>

        {error && (
          <div data-testid="admin-error" className="bg-[#1F0E0E] border border-[#EF4444]/30 p-4 mb-6 flex items-start gap-3">
            <Warning size={20} weight="bold" className="text-[#EF4444] flex-shrink-0" />
            <p className="text-sm text-[#EF4444]">{error}</p>
          </div>
        )}

        {loading ? (
          <p className="text-sm text-[#666] text-center py-12">Loading users…</p>
        ) : users.length === 0 ? (
          <p className="text-sm text-[#666] text-center py-12">No users match your search.</p>
        ) : (
          <div className="space-y-2">
            {users.map((u) => {
              const roleKey = (u.role || 'coach').toLowerCase();
              const meta = ROLE_META[roleKey] || ROLE_META.coach;
              const Icon = meta.icon;
              const isSelf = u.id === me?.id;
              const isOwner = roleKey === 'owner';
              return (
                <div key={u.id} data-testid={`user-row-${u.id}`}
                  className="bg-[#141414] border border-white/10 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-white truncate">{u.name || '—'}</span>
                      {isSelf && <span className="text-[9px] text-[#FBBF24] bg-[#FBBF24]/10 px-1.5 py-0.5 uppercase tracking-wider">You</span>}
                    </div>
                    <p className="text-xs text-[#A3A3A3] mt-0.5 truncate">{u.email}</p>
                    <div className="flex items-center gap-3 mt-2 text-[10px] text-[#666] tracking-wider uppercase">
                      <span>{u.matches_count ?? 0} matches</span>
                      <span>•</span>
                      <span>{u.clips_count ?? 0} clips</span>
                      {u.created_at && (
                        <>
                          <span>•</span>
                          <span>Joined {new Date(u.created_at).toLocaleDateString()}</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-wrap">
                    <span data-testid={`role-chip-${u.id}`}
                      className="flex items-center gap-1.5 text-[10px] font-bold tracking-[0.2em] uppercase px-2.5 py-1.5"
                      style={{ color: meta.color, backgroundColor: `${meta.color}20`, borderColor: `${meta.color}40`, borderWidth: 1, borderStyle: 'solid' }}>
                      <Icon size={12} weight="bold" />
                      {meta.label}
                    </span>

                    <button data-testid={`preview-digest-${u.id}-btn`} onClick={() => openPreview(u)}
                      title="Preview the weekly Coach Pulse email this user would receive"
                      className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-1.5 bg-[#10B981]/10 text-[#10B981] hover:bg-[#10B981]/20 transition-colors border border-[#10B981]/30">
                      <EnvelopeSimple size={14} weight="bold" />
                      <span className="hidden md:inline">Preview Digest</span>
                      <span className="md:hidden">Preview</span>
                    </button>

                    {['coach', 'analyst'].includes(roleKey) ? (
                      <button data-testid={`promote-${u.id}-btn`} onClick={() => setRole(u.id, 'admin')}
                        disabled={busyId === u.id}
                        className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-1.5 bg-[#A855F7]/15 text-[#A855F7] hover:bg-[#A855F7]/25 disabled:opacity-50 transition-colors border border-[#A855F7]/30">
                        <ShieldCheck size={14} weight="bold" />
                        Promote
                      </button>
                    ) : (
                      <button data-testid={`demote-${u.id}-btn`} onClick={() => setRole(u.id, 'coach')}
                        disabled={busyId === u.id || isOwner}
                        title={isOwner ? 'Only an owner can demote another owner' : ''}
                        className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase px-3 py-1.5 bg-white/5 text-[#A3A3A3] hover:bg-white/10 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors border border-white/10">
                        <UserMinus size={14} weight="bold" />
                        Demote
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <p className="text-[10px] text-[#444] tracking-wider mt-8">
          Note: owner-role users can only be changed by another owner. Demotion is blocked if you're the last admin.
        </p>
      </main>

      {/* Preview Digest Modal */}
      {previewUser && (
        <div data-testid="preview-modal-overlay" onClick={() => setPreviewUser(null)}
          className="fixed inset-0 bg-black/80 z-[200] flex items-center justify-center p-4">
          <div onClick={(e) => e.stopPropagation()}
            className="bg-[#0A0A0A] border border-white/10 w-full max-w-3xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-white/10 flex-shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <EnvelopeSimple size={18} weight="bold" className="text-[#10B981] flex-shrink-0" />
                <div className="min-w-0">
                  <h3 className="text-sm font-bold tracking-wider uppercase truncate" style={{ fontFamily: 'Bebas Neue' }}>
                    Coach Pulse Preview
                  </h3>
                  <p className="text-xs text-[#A3A3A3] truncate">For {previewUser.name || previewUser.email}</p>
                </div>
              </div>
              <button data-testid="close-preview-btn" onClick={() => setPreviewUser(null)}
                className="p-2 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] flex-shrink-0">
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 overflow-hidden bg-[#0A0A0A]">
              {loadingPreview ? (
                <p className="text-sm text-[#666] text-center py-12">Rendering preview…</p>
              ) : (
                <iframe data-testid="preview-iframe" title="Coach Pulse digest preview"
                  srcDoc={previewHtml} sandbox="allow-same-origin"
                  className="w-full h-[70vh] border-0 bg-[#0A0A0A]" />
              )}
            </div>
            <div className="p-3 border-t border-white/10 flex-shrink-0 text-[10px] text-[#666] tracking-wider uppercase text-center">
              This is what {previewUser.name || previewUser.email} will receive on Monday's auto-blast.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminUsers;
