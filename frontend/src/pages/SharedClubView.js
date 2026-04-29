import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Shield, Users, ArrowRight, CalendarBlank, Warning } from '@phosphor-icons/react';

const SharedClubView = () => {
  const { shareToken } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/shared/club/${shareToken}`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.status === 404 ? 'notfound' : 'error'));
  }, [shareToken]);

  if (error === 'notfound') {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white flex items-center justify-center px-6">
        <div className="text-center max-w-md">
          <Warning size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Link Unavailable</h1>
          <p className="text-[#A3A3A3]">This club page link has been revoked or never existed.</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#007AFF] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const { club, owner, teams } = data;
  const totalPlayers = teams.reduce((s, t) => s + (t.player_count || 0), 0);

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="shared-club-view">
      <header className="border-b border-white/10 bg-gradient-to-b from-[#0F1A2E] to-[#0A0A0A]">
        <div className="max-w-5xl mx-auto px-6 py-12 flex items-center gap-6">
          {club.logo_url ? (
            <img src={`${API.replace('/api', '')}${club.logo_url}`} alt={club.name}
              className="w-24 h-24 object-contain bg-white/5 p-2 border border-white/10" />
          ) : (
            <div className="w-24 h-24 flex items-center justify-center bg-white/5 border border-white/10">
              <Shield size={48} className="text-[#007AFF]" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#007AFF] mb-1">Public Club Page</div>
            <h1 className="text-5xl lg:text-6xl font-bold leading-none" style={{ fontFamily: 'Bebas Neue' }}>{club.name}</h1>
            <div className="flex items-center gap-3 mt-3 text-sm text-[#A3A3A3]">
              <span>{teams.length} Team{teams.length === 1 ? '' : 's'}</span>
              <span className="text-[#333]">•</span>
              <span className="flex items-center gap-1.5"><Users size={14} /> {totalPlayers} Players</span>
            </div>
            <div className="text-xs text-[#666] mt-2">Director: Coach {owner.name}</div>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-1 h-6 bg-[#007AFF]" />
          <h2 className="text-sm font-bold tracking-[0.2em] uppercase">Teams</h2>
        </div>

        {teams.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-white/10">
            <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
            <p className="text-[#A3A3A3]">No teams in this club yet</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {teams.map(t => {
              const inner = (
                <div className="bg-[#141414] border border-white/10 hover:border-[#007AFF]/40 p-5 flex items-start gap-4 transition-colors group">
                  <Shield size={28} className="text-[#007AFF] flex-shrink-0 mt-1" />
                  <div className="flex-1 min-w-0">
                    <h4 className="font-semibold text-white truncate">{t.name}</h4>
                    <div className="flex items-center gap-3 mt-1 text-xs text-[#A3A3A3]">
                      <span className="flex items-center gap-1"><CalendarBlank size={12} /> {t.season}</span>
                      <span className="text-[#333]">•</span>
                      <span>{t.player_count || 0} players</span>
                    </div>
                    {t.share_token && (
                      <div className="text-[10px] text-[#007AFF] tracking-[0.15em] uppercase mt-2 flex items-center gap-1">
                        View roster <ArrowRight size={12} className="group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    )}
                  </div>
                </div>
              );
              return t.share_token
                ? <Link key={t.id} to={`/shared-team/${t.share_token}`} data-testid={`club-team-${t.id}`}>{inner}</Link>
                : <div key={t.id} data-testid={`club-team-${t.id}`} className="opacity-60 cursor-not-allowed" title="Roster not publicly shared">{inner}</div>;
            })}
          </div>
        )}

        <footer className="pt-12 mt-12 border-t border-white/5 text-center">
          <p className="text-xs text-[#444] tracking-wider">
            Powered by <span className="text-[#007AFF]">Soccer Scout</span>
          </p>
        </footer>
      </main>
    </div>
  );
};

export default SharedClubView;
