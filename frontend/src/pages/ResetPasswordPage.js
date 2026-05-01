import { useState, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Lock, CheckCircle } from '@phosphor-icons/react';

const ResetPasswordPage = () => {
  const [params] = useSearchParams();
  const token = useMemo(() => params.get('token') || '', [params]);
  const [pw1, setPw1] = useState('');
  const [pw2, setPw2] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const navigate = useNavigate();

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (pw1.length < 8) { setError('Password must be at least 8 characters.'); return; }
    if (!/[A-Za-z]/.test(pw1) || !/\d/.test(pw1)) {
      setError('Password must include at least one letter and one digit.');
      return;
    }
    if (pw1 !== pw2) { setError('Passwords do not match.'); return; }
    setBusy(true);
    try {
      await axios.post(`${API}/auth/reset-password`, { token, new_password: pw1 });
      setDone(true);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Reset failed. The link may have expired.');
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-[#0A0A0A]">
        <div className="max-w-md w-full bg-[#141414] border border-white/10 p-8 text-center">
          <h1 className="text-2xl font-bold mb-3" style={{ fontFamily: 'Bebas Neue' }}>Invalid link</h1>
          <p className="text-sm text-[#A3A3A3] mb-6">This page requires a reset token from your email. Check your inbox for the reset link.</p>
          <button data-testid="back-to-login-btn" onClick={() => navigate('/auth')}
            className="w-full bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors">
            Back to login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'linear-gradient(to bottom, #0A0A0A 0%, #141414 100%)' }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src="/logo-mark-256.png" alt="Soccer Scout 11"
            className="mx-auto h-20 w-auto mb-3 drop-shadow-[0_0_24px_rgba(0,122,255,0.3)]" />
          <p className="text-[#A3A3A3] text-sm tracking-wide">Choose a new password</p>
        </div>

        <div className="bg-[#141414] border border-white/10 p-8">
          {done ? (
            <div data-testid="reset-success">
              <div className="flex items-center gap-3 mb-3 text-[#10B981]">
                <CheckCircle size={28} weight="fill" />
                <h2 className="text-xl font-bold" style={{ fontFamily: 'Bebas Neue' }}>Password reset</h2>
              </div>
              <p className="text-sm text-[#CFCFCF] mb-6">You can now sign in with your new password.</p>
              <button data-testid="go-to-login-btn" onClick={() => navigate('/auth')}
                className="w-full bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors">
                Go to login
              </button>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4" data-testid="reset-form">
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">New password</label>
                <div className="relative">
                  <Lock size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                  <input data-testid="reset-pw1-input"
                    type="password" value={pw1} onChange={(e) => setPw1(e.target.value)}
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#007AFF] focus:outline-none"
                    autoFocus required minLength={8} />
                </div>
                <p className="text-[11px] text-[#666] mt-1">Min 8 characters. Must include a letter and a digit.</p>
              </div>

              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Confirm password</label>
                <div className="relative">
                  <Lock size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                  <input data-testid="reset-pw2-input"
                    type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#007AFF] focus:outline-none"
                    required minLength={8} />
                </div>
              </div>

              {error && (
                <div data-testid="reset-error" className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm">
                  {error}
                </div>
              )}

              <button data-testid="reset-submit-btn" type="submit" disabled={busy}
                className="w-full bg-[#007AFF] hover:bg-[#005bb5] text-white py-4 font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
                {busy ? 'Resetting...' : 'Set New Password'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default ResetPasswordPage;
