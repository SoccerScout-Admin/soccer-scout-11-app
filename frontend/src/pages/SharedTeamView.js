import { useState, useEffect, useMemo } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { API } from '../App';
import { Users, UserCircle, Shield, CalendarBlank, FilmStrip, ArrowRight, Warning, Funnel, X } from '@phosphor-icons/react';
import { demographicBadges, classOfLabel } from '../utils/playerDemographics';

const SharedTeamView = () => {
  const { shareToken } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    axios.get(`${API}/shared/team/${shareToken}`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.status === 404 ? 'notfound' : 'error'));
  }, [shareToken]);

  // iter59: URL-driven recruiter filters. Filters are pure derivation off the
  // already-loaded player list (no backend filtering — we keep public payload
  // honest and let the URL describe the scoped view).
  const filterPosition = searchParams.get('position') || '';
  const filterBirthYear = searchParams.get('birth_year') || '';
  const filterClassOf = searchParams.get('class_of') || '';
  const hasFilters = !!(filterPosition || filterBirthYear || filterClassOf);

  const filteredPlayers = useMemo(() => {
    if (!data?.players) return [];
    if (!hasFilters) return data.players;
    return data.players.filter((p) => {
      if (filterPosition && (p.position || '') !== filterPosition) return false;
      if (filterBirthYear && String(p.birth_year ?? '') !== filterBirthYear) return false;
      if (filterClassOf) {
        const co = classOfLabel(p.current_grade);
        if (!co || !co.endsWith(filterClassOf)) return false;
      }
      return true;
    });
  }, [data, hasFilters, filterPosition, filterBirthYear, filterClassOf]);

  const positionGroups = useMemo(() => {
    if (!filteredPlayers.length) return [];
    const groups = { Goalkeeper: [], Defender: [], Midfielder: [], Forward: [], Other: [] };
    const sorted = [...filteredPlayers].sort((a, b) => (a.number ?? 99) - (b.number ?? 99));
    for (const p of sorted) {
      const pos = p.position || 'Other';
      if (groups[pos]) groups[pos].push(p);
      else groups.Other.push(p);
    }
    return Object.entries(groups).filter(([, list]) => list.length > 0);
  }, [filteredPlayers]);

  const clearFilters = () => setSearchParams({});

  if (error === 'notfound') {
    return (
      <div className="min-h-screen bg-[#0A0A0A] text-white flex items-center justify-center px-6">
        <div className="text-center max-w-md">
          <Warning size={64} className="text-[#A3A3A3] mx-auto mb-4" />
          <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: 'Bebas Neue' }}>Link Unavailable</h1>
          <p className="text-[#A3A3A3]">This team page link has been revoked or never existed.</p>
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

  const { team, club, owner, players, shared_matches } = data;

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="shared-team-view">
      {/* Hero */}
      <header className="border-b border-white/10 bg-gradient-to-b from-[#0F1A2E] to-[#0A0A0A]">
        <div className="max-w-5xl mx-auto px-6 py-12">
          <div className="flex items-center gap-6">
            {club?.logo_url ? (
              <img src={`${API.replace('/api', '')}${club.logo_url}`} alt={club.name}
                className="w-20 h-20 object-contain bg-white/5 p-2 border border-white/10" />
            ) : (
              <div className="w-20 h-20 flex items-center justify-center bg-white/5 border border-white/10">
                <Shield size={40} className="text-[#007AFF]" />
              </div>
            )}
            <div className="flex-1">
              <div className="text-[10px] font-bold tracking-[0.3em] uppercase text-[#007AFF] mb-1">Public Team Page</div>
              <h1 className="text-5xl lg:text-6xl font-bold leading-none" style={{ fontFamily: 'Bebas Neue' }}>{team.name}</h1>
              <div className="flex items-center gap-3 mt-3 text-sm text-[#A3A3A3]">
                {club && <span>{club.name}</span>}
                {club && <span className="text-[#333]">•</span>}
                <span className="flex items-center gap-1.5"><CalendarBlank size={14} /> {team.season}</span>
                <span className="text-[#333]">•</span>
                <span className="flex items-center gap-1.5"><Users size={14} /> {players.length} Players</span>
              </div>
              <div className="text-xs text-[#666] mt-2">Coach: {owner.name}</div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10 space-y-12">
        {/* iter59: Recruiter Lens — active filter strip when URL has filter params */}
        {hasFilters && (
          <section data-testid="recruiter-filter-bar"
            className="bg-[#007AFF]/10 border border-[#007AFF]/30 px-5 py-4 flex flex-wrap items-center gap-3">
            <Funnel size={16} weight="fill" className="text-[#007AFF] flex-shrink-0" />
            <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-[#007AFF]">
              Recruiter Lens
            </span>
            {filterClassOf && (
              <span data-testid="active-filter-class-of"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-[#007AFF]/15 border border-[#007AFF]/30 text-[#007AFF] text-xs font-bold tracking-wider uppercase">
                Class of {filterClassOf}
              </span>
            )}
            {filterBirthYear && (
              <span data-testid="active-filter-birth-year"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-[#007AFF]/15 border border-[#007AFF]/30 text-[#007AFF] text-xs font-bold tracking-wider uppercase">
                Born {filterBirthYear}
              </span>
            )}
            {filterPosition && (
              <span data-testid="active-filter-position"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-[#007AFF]/15 border border-[#007AFF]/30 text-[#007AFF] text-xs font-bold tracking-wider uppercase">
                {filterPosition}
              </span>
            )}
            <span data-testid="filter-result-count" className="text-xs text-white ml-auto">
              <span className="font-bold">{filteredPlayers.length}</span>
              <span className="text-[#A3A3A3]"> of {data.players.length}</span> match
            </span>
            <button data-testid="clear-recruiter-filters" onClick={clearFilters}
              className="inline-flex items-center gap-1 text-[10px] font-bold tracking-wider uppercase text-[#007AFF] hover:text-white border border-[#007AFF]/30 hover:border-white/30 px-2.5 py-1 transition-colors">
              <X size={11} /> Clear
            </button>
          </section>
        )}

        {/* Roster */}
        <section data-testid="public-roster">
          <div className="flex items-center gap-2 mb-6">
            <div className="w-1 h-6 bg-[#007AFF]" />
            <h2 className="text-sm font-bold tracking-[0.2em] uppercase">Squad</h2>
          </div>
          {data.players.length === 0 ? (
            <div className="text-center py-16 border border-dashed border-white/10">
              <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
              <p className="text-[#A3A3A3]">No players announced yet</p>
            </div>
          ) : filteredPlayers.length === 0 ? (
            <div data-testid="no-filter-matches" className="text-center py-16 border border-dashed border-white/10">
              <Users size={48} className="text-[#A3A3A3] mx-auto mb-3" />
              <p className="text-[#A3A3A3] mb-3">No players match this filtered view.</p>
              <button data-testid="clear-recruiter-filters-empty" onClick={clearFilters}
                className="text-xs font-bold tracking-wider uppercase text-[#007AFF] hover:text-white">
                See full roster →
              </button>
            </div>
          ) : (
            <div className="space-y-8">
              {positionGroups.map(([position, groupPlayers]) => (
                <div key={position}>
                  <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-3">
                    {position}s ({groupPlayers.length})
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {groupPlayers.map(player => {
                      const badges = demographicBadges(player);
                      return (
                        <div key={player.id} data-testid={`public-player-${player.id}`}
                          className="bg-[#141414] border border-white/10 p-4 flex items-center gap-4 hover:border-[#007AFF]/30 transition-colors">
                          <div className="w-14 h-14 flex-shrink-0 rounded-full bg-[#0A0A0A] border border-white/10 overflow-hidden flex items-center justify-center">
                            {player.profile_pic_url ? (
                              <img src={`${API.replace('/api', '')}${player.profile_pic_url}`} alt={player.name}
                                className="w-full h-full object-cover" />
                            ) : (
                              <UserCircle size={32} className="text-[#333]" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-2xl font-bold text-[#007AFF]" style={{ fontFamily: 'Bebas Neue' }}>
                                {player.number ?? '—'}
                              </span>
                              <h4 className="text-base font-semibold text-white truncate">{player.name}</h4>
                            </div>
                            <p className="text-xs text-[#666] mt-0.5">{player.position || 'No position'}</p>
                            {badges.length > 0 && (
                              <div data-testid={`badges-${player.id}`} className="flex flex-wrap gap-1.5 mt-1.5">
                                {badges.map(({ key, label }) => (
                                  <span key={key}
                                    className="px-1.5 py-0.5 text-[9px] font-bold tracking-wider uppercase bg-[#007AFF]/10 text-[#007AFF] border border-[#007AFF]/30">
                                    {label}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Shared Match Film */}
        {shared_matches.length > 0 && (
          <section data-testid="shared-matches-section">
            <div className="flex items-center gap-2 mb-6">
              <div className="w-1 h-6 bg-[#007AFF]" />
              <h2 className="text-sm font-bold tracking-[0.2em] uppercase">Recent Match Film</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {shared_matches.map(m => (
                <Link key={m.id}
                  to={`/shared/${m.folder_share_token}`}
                  data-testid={`shared-match-link-${m.id}`}
                  className="bg-[#141414] border border-white/10 p-5 flex items-start gap-4 hover:border-[#007AFF]/40 hover:bg-[#1A1A1A] transition-colors group">
                  <FilmStrip size={28} className="text-[#007AFF] flex-shrink-0 mt-1" />
                  <div className="flex-1 min-w-0">
                    <h4 className="font-semibold text-white truncate">
                      {m.team_home} <span className="text-[#666]">vs</span> {m.team_away}
                    </h4>
                    <div className="text-xs text-[#A3A3A3] mt-1">
                      {m.date}
                      {m.competition && <span> • {m.competition}</span>}
                    </div>
                    <div className="text-[10px] text-[#007AFF] tracking-[0.15em] uppercase mt-2 flex items-center gap-1">
                      View in {m.folder_name} <ArrowRight size={12} className="group-hover:translate-x-0.5 transition-transform" />
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}

        <footer className="pt-12 mt-12 border-t border-white/5 text-center">
          <p className="text-xs text-[#444] tracking-wider">Public team page — shared via Soccer Scout</p>
        </footer>
      </main>
    </div>
  );
};

export default SharedTeamView;
