import { SignOut, Shield, Globe, At, Buildings, ChatCircle } from '@phosphor-icons/react';

const NavButton = ({ onClick, testId, mobileTestId, ariaLabel, Icon, colorClass, borderClass, label, badge }) => (
  <>
    <button data-testid={testId} onClick={onClick}
      className={`hidden sm:flex items-center gap-2 px-3 py-1.5 text-xs ${colorClass} hover:text-white hover:bg-[#1F1F1F] transition-colors border ${borderClass} font-bold uppercase tracking-wider relative`}>
      <Icon size={16} weight="bold" /> {label}
      {badge > 0 && (
        <span data-testid="mentions-unread-badge"
          className="absolute -top-1.5 -right-1.5 bg-[#A855F7] text-white text-[9px] font-bold tracking-wider px-1.5 py-0.5 min-w-[18px] text-center">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
    <button data-testid={mobileTestId} onClick={onClick} aria-label={ariaLabel}
      className={`sm:hidden p-2 ${colorClass} border ${borderClass} relative`}>
      <Icon size={18} weight="bold" />
      {badge > 0 && (
        <span className="absolute -top-1.5 -right-1.5 bg-[#A855F7] text-white text-[9px] font-bold tracking-wider px-1.5 py-0.5 min-w-[18px] text-center">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  </>
);

const DashboardHeader = ({ user, unreadMentions, unreadMessages = 0, onNavigate, onLogout }) => {
  const isAdmin = ['admin', 'owner'].includes((user?.role || '').toLowerCase());
  return (
    <header className="sticky top-0 z-50 bg-[#0A0A0A] border-b border-white/10 px-4 sm:px-6 py-3 sm:py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <img src="/logo-mark-96.png" alt="Soccer Scout 11" data-testid="dashboard-logo"
            className="h-7 sm:h-9 w-auto flex-shrink-0" />
        </div>
        <div className="flex items-center gap-2 sm:gap-6 flex-shrink-0">
          <NavButton onClick={() => onNavigate('/scouts')}
            testId="scouts-nav-btn" mobileTestId="scouts-nav-btn-mobile" ariaLabel="Scout Board"
            Icon={Buildings} colorClass="text-[#10B981]" borderClass="border-[#10B981]/30" label="Scouts" />
          <NavButton onClick={() => onNavigate('/messages')}
            testId="messages-nav-btn" mobileTestId="messages-nav-btn-mobile" ariaLabel="Messages"
            Icon={ChatCircle} colorClass="text-[#10B981]" borderClass="border-[#10B981]/30" label="Inbox"
            badge={unreadMessages} />
          <NavButton onClick={() => onNavigate('/clubs')}
            testId="clubs-nav-btn" mobileTestId="clubs-nav-btn-mobile" ariaLabel="Clubs & Teams"
            Icon={Shield} colorClass="text-[#A3A3A3]" borderClass="border-white/10" label="Clubs & Teams" />
          <NavButton onClick={() => onNavigate('/coach-network')}
            testId="coach-network-nav-btn" mobileTestId="coach-network-nav-btn-mobile" ariaLabel="Coach Network"
            Icon={Globe} colorClass="text-[#A855F7]" borderClass="border-[#A855F7]/30" label="Coach Network" />
          <NavButton onClick={() => onNavigate('/mentions')}
            testId="mentions-nav-btn" mobileTestId="mentions-nav-btn-mobile" ariaLabel="Mentions"
            Icon={At} colorClass="text-[#A855F7]" borderClass="border-[#A855F7]/30" label="Mentions"
            badge={unreadMentions} />
          {isAdmin && (
            <NavButton onClick={() => onNavigate('/admin/users')}
              testId="admin-nav-btn" mobileTestId="admin-nav-btn-mobile" ariaLabel="Admin"
              Icon={Shield} colorClass="text-[#FBBF24]" borderClass="border-[#FBBF24]/30" label="Admin" />
          )}
          <div className="hidden md:block text-right">
            <p className="text-sm text-[#A3A3A3]">{user?.name}</p>
            <p className="text-xs text-[#A3A3A3] uppercase tracking-wider">{user?.role}</p>
          </div>
          <button data-testid="logout-btn" onClick={onLogout} aria-label="Logout"
            className="p-2 hover:bg-[#1F1F1F] transition-colors border border-white/10">
            <SignOut size={20} className="text-[#A3A3A3]" />
          </button>
        </div>
      </div>
    </header>
  );
};

export default DashboardHeader;
