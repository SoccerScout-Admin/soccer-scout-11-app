/**
 * SentLensLinksPanel
 * ------------------
 * Read-only table of lens-link outreach emails the coach has sent for THIS
 * team, with click counts + last-clicked timestamps. Auto-refreshes when a
 * new link is sent (parent passes `refreshKey` to bust the cache).
 *
 * Renders nothing if the coach hasn't sent any lens links for this team yet —
 * we don't want the team roster page cluttered for coaches who haven't
 * adopted the feature.
 */
import { useState, useEffect } from 'react';
import axios from 'axios';
import { API, getAuthHeader } from '../../App';
import { Funnel, CursorClick, Clock, EnvelopeSimple } from '@phosphor-icons/react';

const formatRelative = (iso) => {
  if (!iso) return 'Never';
  const then = new Date(iso).getTime();
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  const days = Math.floor(seconds / 86400);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
};

const filterSummary = (filters) => {
  if (!filters) return 'Full Squad';
  const parts = [];
  if (filters.class_of) parts.push(`Class of ${filters.class_of}`);
  if (filters.birth_year) parts.push(`Born ${filters.birth_year}`);
  if (filters.position) parts.push(filters.position);
  return parts.length ? parts.join(' · ') : 'Full Squad';
};

const SentLensLinksPanel = ({ teamId, refreshKey = 0 }) => {
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    axios.get(`${API}/lens-links`, {
      params: { team_id: teamId },
      headers: getAuthHeader(),
    })
      .then((res) => { if (!cancelled) setLinks(res.data); })
      .catch(() => { if (!cancelled) setLinks([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [teamId, refreshKey]);

  if (loading) return null;
  if (!links.length) return null;

  return (
    <section data-testid="sent-lens-links-panel" className="mb-8">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-1 h-5 bg-[#10B981]" />
        <h2 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">
          Recruiter Outreach ({links.length})
        </h2>
      </div>
      <div className="border border-white/10 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#0A0A0A]">
            <tr className="text-[10px] uppercase tracking-wider text-[#A3A3A3]">
              <th className="px-4 py-2 text-left">Recipient</th>
              <th className="px-4 py-2 text-left">Filter</th>
              <th className="px-4 py-2 text-right">Clicks</th>
              <th className="px-4 py-2 text-right">Last Opened</th>
              <th className="px-4 py-2 text-right">Sent</th>
            </tr>
          </thead>
          <tbody>
            {links.map((link) => (
              <tr key={link.id} data-testid={`lens-link-${link.id}`}
                className="border-t border-white/5 bg-[#141414] hover:bg-[#1A1A1A] transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 text-white truncate">
                    <EnvelopeSimple size={14} className="text-[#666] flex-shrink-0" />
                    <span className="truncate">{link.recipient_name || link.recipient_email}</span>
                  </div>
                  {link.recipient_name && (
                    <div className="text-[10px] text-[#666] truncate ml-6">{link.recipient_email}</div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold tracking-wider uppercase bg-[#10B981]/10 border border-[#10B981]/30 text-[#10B981] px-2 py-0.5">
                    <Funnel size={10} weight="fill" />
                    {filterSummary(link.filters)}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span data-testid={`click-count-${link.id}`}
                    className={`inline-flex items-center gap-1 font-bold tabular-nums ${
                      link.click_count > 0 ? 'text-[#10B981]' : 'text-[#666]'
                    }`}>
                    <CursorClick size={14} weight={link.click_count > 0 ? 'fill' : 'regular'} />
                    {link.click_count}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-xs text-[#A3A3A3]">
                  <span className="inline-flex items-center gap-1">
                    <Clock size={12} className="text-[#666]" />
                    {formatRelative(link.last_clicked_at)}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-xs text-[#666] tabular-nums">
                  {formatRelative(link.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};

export default SentLensLinksPanel;
