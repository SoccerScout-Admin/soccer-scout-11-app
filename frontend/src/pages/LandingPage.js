import { useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Video, Crosshair, ChartLineUp, PlayCircle, Sparkle, FilmReel, FacebookLogo,
  TwitterLogo, InstagramLogo, ArrowRight,
} from '@phosphor-icons/react';
import '../styles/logo-intro.css';

const NAV_LINKS = [
  { id: 'home', label: 'Home' },
  { id: 'features', label: 'Features' },
  { id: 'pricing', label: 'Pricing' },
  { id: 'about', label: 'About' },
  { id: 'contact', label: 'Contact' },
];

const FEATURES = [
  {
    icon: Video,
    title: 'Video Analysis',
    blurb: 'Upload full-match footage. Gemini AI generates tactical breakdowns, key moments, and timeline markers within minutes — no scrubbing required.',
  },
  {
    icon: Crosshair,
    title: 'Player Tracking',
    blurb: 'Auto-zoom highlights crop tight to the ball and the players involved. Every goal gets a wide + close-up stitched version automatically.',
  },
  {
    icon: ChartLineUp,
    title: 'Performance Reports',
    blurb: 'Season trends, player dossiers, and AI match recaps. Share rich public OG cards with college coaches and recruiters.',
  },
];

const scrollToId = (id) => {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

const LandingPage = ({ isAuthenticated }) => {
  const navigate = useNavigate();

  useEffect(() => {
    // Plays the intro logo on first visit per session
    try {
      sessionStorage.setItem('logo-intro-played', '1');
    } catch { /* sessionStorage blocked */ }
  }, []);

  const ctaPrimary = isAuthenticated ? '/dashboard' : '/auth';
  const handleLogin = () => navigate('/auth');
  const handleRegister = () => navigate('/auth?mode=register');

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="landing-page">
      {/* Top Nav */}
      <header className="sticky top-0 z-40 bg-[#0A0A0A]/95 backdrop-blur border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-3">
          <button
            data-testid="brand-logo"
            onClick={() => scrollToId('home')}
            className="flex items-center gap-2 sm:gap-3 group">
            <img src="/logo-mark-96.png" alt="" className="h-8 sm:h-10 w-auto" />
            <span className="text-lg sm:text-2xl font-bold tracking-wider leading-none" style={{ fontFamily: 'Bebas Neue' }}>
              SOCCER<span className="text-[#007AFF]"> SCOUT 11</span>
            </span>
          </button>
          <nav className="hidden md:flex items-center gap-6">
            {NAV_LINKS.map((l) => (
              <button
                key={l.id}
                data-testid={`nav-${l.id}`}
                onClick={() => scrollToId(l.id)}
                className="text-sm tracking-wider uppercase font-bold text-[#A3A3A3] hover:text-white transition-colors">
                {l.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-2 sm:gap-3">
            {isAuthenticated ? (
              <Link
                to="/dashboard"
                data-testid="cta-dashboard-header"
                className="flex items-center gap-1.5 bg-[#007AFF] hover:bg-[#005bb5] text-white px-4 sm:px-5 py-2 text-xs sm:text-sm font-bold tracking-wider uppercase transition-colors">
                Dashboard <ArrowRight size={14} weight="bold" />
              </Link>
            ) : (
              <>
                <button
                  data-testid="login-btn-header"
                  onClick={handleLogin}
                  className="hidden sm:inline-block text-sm tracking-wider uppercase font-bold text-[#A3A3A3] hover:text-white transition-colors">
                  Log in
                </button>
                <button
                  data-testid="register-btn-header"
                  onClick={handleRegister}
                  className="bg-[#007AFF] hover:bg-[#005bb5] text-white px-4 sm:px-5 py-2 text-xs sm:text-sm font-bold tracking-wider uppercase transition-colors">
                  Register
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Hero */}
      <section
        id="home"
        className="relative overflow-hidden border-b border-white/10"
        style={{
          background:
            'radial-gradient(circle at 20% 30%, rgba(0,122,255,0.15), transparent 50%), radial-gradient(circle at 80% 70%, rgba(16,185,129,0.12), transparent 50%)',
        }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-20 sm:pb-32 text-center">
          <div className="inline-flex items-center gap-2 border border-[#007AFF]/30 bg-[#007AFF]/10 px-3 py-1 mb-8">
            <Sparkle size={12} weight="fill" className="text-[#007AFF]" />
            <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#007AFF]">Built for Coaches & Recruiters</span>
          </div>
          <h1
            data-testid="hero-title"
            className="text-4xl sm:text-6xl lg:text-7xl font-bold mb-6 leading-[0.95] tracking-tight uppercase"
            style={{ fontFamily: 'Bebas Neue' }}>
            Professional Player Analysis
            <br />
            <span className="text-[#007AFF]">& Scouting Made Simple</span>
          </h1>
          <p className="text-base sm:text-lg text-[#A3A3A3] max-w-2xl mx-auto mb-10 leading-relaxed">
            Upload match film, get instant AI-powered tactical breakdowns, share branded highlight reels,
            and post recruiting listings — all on one platform.
          </p>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3 sm:gap-4">
            <Link
              to={ctaPrimary}
              data-testid="hero-cta-upload"
              className="flex items-center justify-center gap-2 bg-[#007AFF] hover:bg-[#005bb5] text-white px-8 py-4 text-sm font-bold tracking-wider uppercase transition-colors">
              <Video size={18} weight="bold" /> Upload Video
            </Link>
            <Link
              to={ctaPrimary}
              data-testid="hero-cta-create"
              className="flex items-center justify-center gap-2 border border-[#10B981] text-[#10B981] hover:bg-[#10B981] hover:text-black px-8 py-4 text-sm font-bold tracking-wider uppercase transition-colors">
              <PlayCircle size={18} weight="bold" /> Create Game
            </Link>
          </div>
          <p className="mt-8 text-[10px] tracking-[0.2em] uppercase text-[#666]">
            Trusted by coaches across NCAA D1 · ECNL · MLS Next
          </p>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 sm:py-28 border-b border-white/10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="text-center mb-12 sm:mb-16">
            <p className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#007AFF] mb-3">
              What You Get
            </p>
            <h2 className="text-3xl sm:text-5xl font-bold uppercase mb-4" style={{ fontFamily: 'Bebas Neue' }}>
              Built for the Modern Coach
            </h2>
            <p className="text-sm sm:text-base text-[#A3A3A3] max-w-2xl mx-auto">
              From upload to recruiter-ready reel in under 10 minutes.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 sm:gap-6">
            {FEATURES.map((f, idx) => {
              const Icon = f.icon;
              return (
                <div
                  key={f.title}
                  data-testid={`feature-card-${idx}`}
                  className="bg-[#141414] border border-white/10 hover:border-[#007AFF]/40 p-6 sm:p-8 transition-colors group">
                  <div className="w-12 h-12 bg-[#007AFF]/10 border border-[#007AFF]/30 flex items-center justify-center mb-5 group-hover:bg-[#007AFF]/20 transition-colors">
                    <Icon size={24} weight="bold" className="text-[#007AFF]" />
                  </div>
                  <h3 className="text-xl sm:text-2xl font-bold uppercase tracking-wider mb-3 text-white" style={{ fontFamily: 'Bebas Neue' }}>
                    {f.title}
                  </h3>
                  <p className="text-sm text-[#A3A3A3] leading-relaxed">{f.blurb}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="py-20 sm:py-28 border-b border-white/10 bg-gradient-to-b from-transparent to-[#0A0A0A]/50">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 text-center">
          <p className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#10B981] mb-3">Pricing</p>
          <h2 className="text-3xl sm:text-5xl font-bold uppercase mb-6" style={{ fontFamily: 'Bebas Neue' }}>
            Free While We're in Beta
          </h2>
          <p className="text-sm sm:text-base text-[#A3A3A3] max-w-2xl mx-auto mb-10 leading-relaxed">
            Soccer Scout 11 is free for individual coaches and players during the beta.
            Paid team plans launch later — early users keep founder pricing.
          </p>
          <Link
            to={ctaPrimary}
            data-testid="pricing-cta"
            className="inline-flex items-center gap-2 bg-[#10B981] hover:bg-[#0e9d6c] text-black px-8 py-4 text-sm font-bold tracking-wider uppercase transition-colors">
            <Sparkle size={16} weight="fill" /> Get Started Free
          </Link>
        </div>
      </section>

      {/* About */}
      <section id="about" className="py-20 sm:py-28 border-b border-white/10">
        <div className="max-w-4xl mx-auto px-4 sm:px-6">
          <p className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#FBBF24] mb-3 text-center">About</p>
          <h2 className="text-3xl sm:text-5xl font-bold uppercase mb-8 text-center" style={{ fontFamily: 'Bebas Neue' }}>
            Coaches Building For Coaches
          </h2>
          <div className="space-y-4 text-sm sm:text-base text-[#A3A3A3] leading-relaxed">
            <p>
              Soccer Scout 11 started as one coach's spreadsheet — clip times, player notes, and a
              folder of mp4s scattered across three laptops. We rebuilt that workflow as an AI-first
              platform so every coach can move from raw footage to recruiter-ready analysis in minutes.
            </p>
            <p>
              Under the hood we run Gemini 3.1 for video understanding, ffmpeg for adaptive zoom +
              concat, and a chunked upload pipeline that handles 4K full-match files without
              choking. Everything runs on a tight feedback loop with the coaches using it daily.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-4 mt-10 text-center">
            <div className="border border-white/10 p-5">
              <div className="text-4xl sm:text-5xl font-bold text-[#007AFF] mb-1" style={{ fontFamily: 'Bebas Neue' }}>5x</div>
              <div className="text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3]">Faster than manual breakdown</div>
            </div>
            <div className="border border-white/10 p-5">
              <div className="text-4xl sm:text-5xl font-bold text-[#10B981] mb-1" style={{ fontFamily: 'Bebas Neue' }}>60-90s</div>
              <div className="text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3]">Auto highlight reel</div>
            </div>
            <div className="border border-white/10 p-5">
              <div className="text-4xl sm:text-5xl font-bold text-[#FBBF24] mb-1" style={{ fontFamily: 'Bebas Neue' }}>0$</div>
              <div className="text-[10px] tracking-[0.2em] uppercase text-[#A3A3A3]">Beta access cost</div>
            </div>
          </div>
        </div>
      </section>

      {/* Contact */}
      <section id="contact" className="py-20 sm:py-28">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 text-center">
          <p className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#A855F7] mb-3">Contact</p>
          <h2 className="text-3xl sm:text-5xl font-bold uppercase mb-6" style={{ fontFamily: 'Bebas Neue' }}>
            Let's Talk
          </h2>
          <p className="text-sm sm:text-base text-[#A3A3A3] max-w-xl mx-auto mb-8 leading-relaxed">
            Questions about uploading large match film, integrating with your club's existing
            scouting workflow, or pricing for a team? Reach out — we read every email.
          </p>
          <a
            href="mailto:bb@soccerscout11.com"
            data-testid="contact-email-cta"
            className="inline-flex items-center gap-2 border border-[#007AFF] text-[#007AFF] hover:bg-[#007AFF] hover:text-white px-8 py-4 text-sm font-bold tracking-wider uppercase transition-colors">
            bb@soccerscout11.com
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/10 py-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <img src="/logo-mark-96.png" alt="" className="h-6 w-auto" />
            <span className="text-[10px] tracking-[0.2em] uppercase font-bold text-[#666]">
              © {new Date().getFullYear()} Soccer Scout 11
            </span>
          </div>
          <div className="flex items-center gap-3 text-[#666]">
            <a href="#" aria-label="Twitter" className="hover:text-white transition-colors"><TwitterLogo size={18} /></a>
            <a href="#" aria-label="Instagram" className="hover:text-white transition-colors"><InstagramLogo size={18} /></a>
            <a href="#" aria-label="Facebook" className="hover:text-white transition-colors"><FacebookLogo size={18} /></a>
            <Link
              to="/reels"
              data-testid="footer-reel-library"
              className="text-[10px] tracking-[0.2em] uppercase ml-2 hover:text-white transition-colors flex items-center gap-1">
              <FilmReel size={12} className="inline" />
              Reel Library
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;
