import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API, getAuthHeader, getCurrentUser } from '../App';
import { ShieldCheck, Lock } from '@phosphor-icons/react';

const AdminClaim = () => {
  const [secret, setSecret] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const navigate = useNavigate();
  const user = getCurrentUser();

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const res = await axios.post(`${API}/admin/bootstrap`,
        { secret: secret.trim() },
        { headers: getAuthHeader() });
      setResult(res.data);
      // Refresh the user cache so /auth/me picks up the new role on next nav.
      try {
        const me = await axios.get(`${API}/auth/me`, { headers: getAuthHeader() });
        localStorage.setItem('user', JSON.stringify({
          id: me.data.id, name: me.data.name, role: me.data.role,
        }));
      } catch { /* silent */ }
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not elevate. Check the secret.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-[#0A0A0A]">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-[#A855F7]/15 border border-[#A855F7]/30 mb-3">
            <ShieldCheck size={28} className="text-[#A855F7]" />
          </div>
          <h1 className="text-3xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Claim Admin</h1>
          <p className="text-xs text-[#A3A3A3] mt-1 tracking-wide">Elevate <span className="text-white">{user?.name || 'your account'}</span> to admin</p>
        </div>

        <div className="bg-[#141414] border border-white/10 p-8">
          {result ? (
            <div data-testid="claim-success">
              <h2 className="text-xl font-bold text-[#10B981] mb-2" style={{ fontFamily: 'Bebas Neue' }}>
                {result.status === 'already_admin' ? "You're already admin" : 'Admin access granted'}
              </h2>
              <p className="text-sm text-[#CFCFCF] mb-6">Role is now <span className="text-white font-semibold">{result.role}</span>. Admin endpoints are unlocked for this account.</p>
              <div className="flex gap-3">
                <button data-testid="go-dashboard-btn" onClick={() => navigate('/')}
                  className="flex-1 border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">Dashboard</button>
                <button data-testid="go-admin-users-btn" onClick={() => navigate('/admin/users')}
                  className="flex-1 bg-[#A855F7] hover:bg-[#9233ea] text-white py-3 font-bold tracking-wider uppercase transition-colors">Open Admin</button>
              </div>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4" data-testid="claim-form">
              <p className="text-sm text-[#A3A3A3]">Paste the admin bootstrap secret from your server .env. This is a one-time rescue for environments without an existing admin.</p>
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Bootstrap Secret</label>
                <div className="relative">
                  <Lock size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                  <input data-testid="claim-secret-input"
                    type="password" value={secret} onChange={(e) => setSecret(e.target.value)}
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#A855F7] focus:outline-none font-mono text-sm"
                    autoFocus required />
                </div>
              </div>
              {error && (
                <div data-testid="claim-error" className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm">{error}</div>
              )}
              <button data-testid="claim-submit-btn" type="submit" disabled={busy}
                className="w-full bg-[#A855F7] hover:bg-[#9233ea] text-white py-4 font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
                {busy ? 'Elevating...' : 'Elevate to Admin'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default AdminClaim;
