import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Play, User, Lock, Envelope } from '@phosphor-icons/react';

const AuthPage = ({ setIsAuthenticated }) => {
  const [isLogin, setIsLogin] = useState(true);
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

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'linear-gradient(to bottom, #0A0A0A 0%, #141414 100%)' }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center mb-4">
            <Play size={48} weight="fill" className="text-[#007AFF]" />
          </div>
          <h1 className="text-5xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>SOCCER SCOUT</h1>
          <p className="text-[#A3A3A3] text-sm tracking-wide">AI-Powered Match Analysis Platform</p>
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
    </div>
  );
};

export default AuthPage;
