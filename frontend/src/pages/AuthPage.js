import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { User, Lock, Envelope } from '@phosphor-icons/react';
import '../styles/logo-intro.css';

const AuthPage = ({ setIsAuthenticated }) => {
  const [isLogin, setIsLogin] = useState(true);
  const [showForgot, setShowForgot] = useState(false);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotSent, setForgotSent] = useState(false);
  const [forgotBusy, setForgotBusy] = useState(false);
  // Show the intro animation only on the first time per session — returning
  // users skip it. Computed at mount so re-renders don't re-fire it.
  const showIntro = useMemo(() => {
    try {
      if (sessionStorage.getItem('logo-intro-played')) return false;
      sessionStorage.setItem('logo-intro-played', '1');
      return true;
    } catch { return false; }
  }, []);
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    name: '',
    role: 'analyst'
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const endpoint = isLogin ? '/auth/login' : '/auth/register';
      const payload = isLogin
        ? { email: formData.email, password: formData.password }
        : formData;

      const response = await axios.post(`${API}${endpoint}`, payload);
      localStorage.setItem('token', response.data.token);
      // Cache only non-sensitive fields — drop email and any future PII.
      const u = response.data.user || {};
      localStorage.setItem('user', JSON.stringify({
        id: u.id, name: u.name, role: u.role,
      }));
      setIsAuthenticated(true);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.detail || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  const handleForgot = async (e) => {
    e.preventDefault();
    if (!forgotEmail.trim()) return;
    setForgotBusy(true);
    try {
      await axios.post(`${API}/auth/forgot-password`, { email: forgotEmail.trim() });
      setForgotSent(true);
    } catch (err) {
      // The backend intentionally returns 200 regardless to prevent
      // enumeration, so errors here would be network-level only.
      setForgotSent(true);
    } finally {
      setForgotBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'linear-gradient(to bottom, #0A0A0A 0%, #141414 100%)' }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src="/logo-mark-256.png" alt="Soccer Scout 11" data-testid="auth-logo"
            className={`mx-auto h-24 sm:h-28 w-auto mb-4 drop-shadow-[0_0_28px_rgba(0,122,255,0.35)] ${showIntro ? 'logo-intro' : ''}`} />
          <p data-testid="auth-tagline" className={`text-[#A3A3A3] text-sm tracking-wide ${showIntro ? 'logo-intro-tagline' : ''}`}>
            AI-Powered Match Analysis Platform
          </p>
        </div>

        <div className="bg-[#141414] border border-white/10 p-8">
          <div className="flex mb-6">
            <button
              data-testid="login-tab-btn"
              onClick={() => setIsLogin(true)}
              className={`flex-1 py-3 text-sm font-bold tracking-wider uppercase transition-colors ${
                isLogin ? 'text-white border-b-2 border-[#007AFF]' : 'text-[#A3A3A3] border-b border-white/10'
              }`}
            >
              Login
            </button>
            <button
              data-testid="register-tab-btn"
              onClick={() => setIsLogin(false)}
              className={`flex-1 py-3 text-sm font-bold tracking-wider uppercase transition-colors ${
                !isLogin ? 'text-white border-b-2 border-[#007AFF]' : 'text-[#A3A3A3] border-b border-white/10'
              }`}
            >
              Register
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Name</label>
                <div className="relative">
                  <User size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                  <input
                    data-testid="name-input"
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#007AFF] focus:outline-none"
                    required={!isLogin}
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Email</label>
              <div className="relative">
                <Envelope size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                <input
                  data-testid="email-input"
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Password</label>
              <div className="relative">
                <Lock size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                <input
                  data-testid="password-input"
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#007AFF] focus:outline-none"
                  required
                />
              </div>
              {isLogin && (
                <button type="button" data-testid="forgot-password-link"
                  onClick={() => { setShowForgot(true); setForgotSent(false); setForgotEmail(formData.email); }}
                  className="mt-2 text-xs text-[#007AFF] hover:underline">
                  Forgot password?
                </button>
              )}
            </div>

            {!isLogin && (
              <div>
                <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Role</label>
                <select
                  data-testid="role-select"
                  value={formData.role}
                  onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                  className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
                >
                  <option value="coach">Coach</option>
                  <option value="analyst">Analyst</option>
                  <option value="player">Player</option>
                </select>
              </div>
            )}

            {error && (
              <div data-testid="auth-error" className="bg-[#FF3B30]/10 border border-[#FF3B30] text-[#FF3B30] px-4 py-3 text-sm">
                {error}
              </div>
            )}

            <button
              data-testid="auth-submit-btn"
              type="submit"
              disabled={loading}
              className="w-full bg-[#007AFF] hover:bg-[#005bb5] text-white py-4 font-bold tracking-wider uppercase transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Processing...' : isLogin ? 'Login' : 'Create Account'}
            </button>
          </form>
        </div>
      </div>

      {showForgot && (
        <div data-testid="forgot-password-modal"
          className="fixed inset-0 z-50 bg-black/70 flex items-start justify-center overflow-y-auto"
          onClick={() => setShowForgot(false)}>
          <div className="bg-[#141414] border border-white/10 max-w-md w-full mx-auto my-8 p-8"
            onClick={(e) => e.stopPropagation()}>
            <h3 className="text-2xl font-bold mb-3" style={{ fontFamily: 'Bebas Neue' }}>Forgot password</h3>
            {forgotSent ? (
              <div>
                <p className="text-sm text-[#CFCFCF] mb-6">
                  If an account exists for <span className="text-white font-semibold">{forgotEmail}</span>, you'll receive a reset link at that address shortly. It expires in 60 minutes.
                </p>
                <button data-testid="forgot-close-btn" onClick={() => setShowForgot(false)}
                  className="w-full bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors">Close</button>
              </div>
            ) : (
              <form onSubmit={handleForgot}>
                <p className="text-sm text-[#A3A3A3] mb-4">Enter your email and we'll send you a secure reset link.</p>
                <div className="relative mb-5">
                  <Envelope size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A3A3A3]" />
                  <input data-testid="forgot-email-input"
                    type="email" value={forgotEmail}
                    onChange={(e) => setForgotEmail(e.target.value)}
                    className="w-full bg-[#0A0A0A] border border-white/10 text-white pl-12 pr-4 py-3 focus:border-[#007AFF] focus:outline-none"
                    placeholder="you@example.com" required autoFocus />
                </div>
                <div className="flex gap-3">
                  <button type="button" onClick={() => setShowForgot(false)}
                    className="flex-1 border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">Cancel</button>
                  <button data-testid="forgot-submit-btn" type="submit" disabled={forgotBusy}
                    className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
                    {forgotBusy ? 'Sending...' : 'Send Reset Link'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AuthPage;
